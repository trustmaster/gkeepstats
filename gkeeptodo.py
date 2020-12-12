#!/usr/local/bin/python3
from argparse import ArgumentParser
from configparser import ConfigParser
import csv
from datetime import date, datetime
from enum import Enum
import getpass
import os
import re

from dateutil.relativedelta import relativedelta
from gkeepapi import Keep, node
import keyring


class Mode(Enum):
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'
    TOTAL = 'total'

    @staticmethod
    def from_str(s: str):
        return {
            'daily': Mode.DAILY,
            'weekly': Mode.WEEKLY,
            'monthly': Mode.MONTHLY,
            'yearly': Mode.YEARLY,
            'total': Mode.TOTAL
        }[s]


default_formats = {
    Mode.DAILY: '%Y-%m-%d',
    Mode.WEEKLY: '%Y-W%W',
    Mode.MONTHLY: '%b %Y',
    Mode.YEARLY: '%Y',
}


colors = {
    'blue': node.ColorValue.Blue,
    'brown': node.ColorValue.Brown,
    'dark-blue': node.ColorValue.DarkBlue,
    'gray': node.ColorValue.Gray,
    'green': node.ColorValue.Green,
    'orange': node.ColorValue.Orange,
    'pink': node.ColorValue.Pink,
    'purple': node.ColorValue.Purple,
    'red': node.ColorValue.Red,
    'teal': node.ColorValue.Teal,
    'white': node.ColorValue.White,
    'yellow': node.ColorValue.Yellow,
}


def parse_modes(list_str: str) -> list[Mode]:
    items = list_str.split(',')
    modes = [Mode.from_str(s.strip()) for s in items]

    return modes


def id_to_date(formats: dict[Mode, str], id: str) -> date:
    for key in formats:
        id_s = id
        format = formats[key]
        if key is Mode.WEEKLY:
            # Weekly format needs a day of the week to extract full date
            id_s = id + '-1'  # append Monday
            format = formats[key] + '-%w'  # append day of the week pattern
        try:
            # print(f'trying {id_s} as {format}')
            dtime = datetime.strptime(id_s, format)
            if dtime:
                # print(f'parsed {id_s} as {format} to {dtime}')
                return dtime.date()
        except:
            continue
    return None


class DataPoint:
    def __init__(self, id: str, date: date, checked: int, unchecked: int):
        self.id = id
        self.date = date
        self.checked = checked
        self.unchecked = unchecked
        self.total = checked + unchecked
        self.completion = 0
        if self.total > 0:
            self.completion = checked / self.total


class Metric:
    formats = default_formats

    def __init__(self, name: str, keyword: str, modes_s: str):
        self.name = name
        self.keyword = keyword
        self.modes = parse_modes(modes_s)
        self.data = []

    # add_data_point adds a data point only if id matches one of the recognized date formats
    def add_data_point(self, id: str, checked: int, unchecked: int) -> bool:
        d = id_to_date(Metric.formats, id)
        if d is None:
            return False

        self.data.append(DataPoint(id, d, checked, unchecked))
        return True

    def sort(self):
        self.data.sort(key=lambda p: p.date)

    def total(self) -> DataPoint:
        res = DataPoint(Mode.TOTAL.value, date.today(), 0, 0)
        for p in self.data:
            res.checked += p.checked
            res.unchecked += p.unchecked
            res.total += p.total
        if res.total > 0:
            res.completion = res.checked / res.total
        return res

    def series(self, mode: Mode) -> list[DataPoint]:
        if mode is Mode.TOTAL:
            # Total stats have simple heuristics
            p = self.total()
            return [p]

        res = []
        i = -1
        last_id = None

        for p in self.data:
            id = p.date.strftime(Metric.formats[mode])
            if id != last_id:
                if i >= 0 and res[i].total > 0:
                    # Update completion rate for last aggregate
                    res[i].completion = res[i].checked / res[i].total
                i += 1
                last_id = id
                p.id = id
                res.append(p)
                continue

            res[i].checked += p.checked
            res[i].unchecked += p.unchecked
            res[i].total += p.total

        if i >= 0 and res[i].total > 0:
            # Update completion rate for last aggregate
            res[i].completion = res[i].checked / res[i].total

        return res


class Todo:
    def __init__(self, title: str, items: list[str], labels: list[str], color: str):
        self.title = title
        self.items = items
        self.labels = labels
        self.color = color


class Template:
    def __init__(self, name: str, title: str, mode: Mode, format: str, items_s: str, labels_s: str, color: str):
        self.name = name
        self.title = title
        self.mode = mode
        items = items_s.split(',')
        self.format = format
        self.items = [s.strip() for s in items]
        labels = labels_s.split(',')
        self.labels = [s.strip() for s in labels]
        self.color = node.ColorValue.White
        if color in colors:
            self.color = colors[color]

    def date_to_id(self, d: date) -> str:
        return d.strftime(self.format)

    def add_delta(self, d: date) -> date:
        delta = relativedelta(days=1)
        if self.mode == Mode.YEARLY:
            delta = relativedelta(years=+1)
        elif self.mode == Mode.MONTHLY:
            delta = relativedelta(months=+1)
        elif self.mode == Mode.WEEKLY:
            delta = relativedelta(weeks=+1)
        return d + delta

    def generate(self, from_date: date, to_date: date) -> list[Todo]:
        res = []
        if to_date < from_date:
            return res

        d = from_date
        while d <= to_date:
            id = self.date_to_id(d)
            title = self.title.replace('{date}', id)
            todo = Todo(title, self.items, self.labels, self.color)

            res.append(todo)

            d = self.add_delta(d)

        return res


def get_config(path='gkeeptodo.ini'):
    if not os.path.isfile(path):
        print(f'Config file {path} not found')
        exit()

    ini = ConfigParser(interpolation=None)
    ini.read(path)

    return ini


def get_metrics_from_config(config: ConfigParser) -> dict[str, Metric]:
    metrics = {}
    for s in config.sections():
        if s.startswith('metric:'):
            name = s[len('metric:'):].lstrip()
            m = Metric(name, config[s]['keyword'], config[s]['modes'])
            metrics[s] = m
    return metrics


def get_templates_from_config(config: ConfigParser, formats: dict[Mode, str]) -> dict[str, Template]:
    templates = {}
    for s in config.sections():
        if s.startswith('template:'):
            name = s[len('template:'):].lstrip()
            mode = Mode.from_str(config[s]['mode'].strip())
            format = formats[mode]
            labels = []
            if 'labels' in config[s]:
                labels = config[s]['labels']
            color = 'white'
            if 'color' in config[s]:
                color = config[s]['color']
            t = Template(name, config[s]['title'], mode, format,
                         config[s]['items'], labels, color)
            templates[s] = t
    return templates


def get_formats(config: ConfigParser) -> dict[Mode, str]:
    formats = default_formats
    if 'formats' in config.sections():
        for key in config['formats']:
            mode = Mode.from_str(key)
            format = config['formats'][key]
            formats[mode] = format
    return formats


def load_metric_datapoints(keep: Keep, m: Metric) -> Metric:
    notes = keep.find(query=m.keyword)

    for note in notes:
        if not hasattr(note, 'items'):
            continue
        # strip keyword and spaces from title
        id = note.title.removeprefix(m.keyword).removesuffix(m.keyword).strip()
        m.add_data_point(id, len(note.checked), len(note.unchecked))

    return m


def write_series_to_csv_file(fname: str, series: list[DataPoint]):
    with open(fname, 'w') as csvfile:
        writer = csv.writer(csvfile)
        # Write header
        writer.writerow(
            ['Index', 'Checked', 'Unchecked', 'Total', 'Completion'])
        for p in series:
            writer.writerow(
                [p.id, p.checked, p.unchecked, p.total, p.completion])


def add_todo(keep: Keep, todo: Todo, labels: list[node.Label]) -> node.List:
    items = []
    for item in todo.items:
        items.append((item, False))
    note = keep.createList(todo.title, items)
    note.color = todo.color
    for label in labels:
        note.labels.add(label)
    return note


def login(keep: Keep, email: str):
    print('Logging in')
    password = getpass.getpass('Password: ')
    print('Authenticating, this may take a while...')
    try:
        keep.login(email, password)
    except:
        print('Authentication failed')
        exit()

    # Save the auth token in keyring
    print('Authentication is successful, saving token in keyring')
    token = keep.getMasterToken()
    keyring.set_password('gkeeptodo', email, token)
    print('Token saved. Have fun with other commands!')


def resume(keep: Keep, email: str):
    print('Loading access token from keyring')
    token = keyring.get_password('gkeeptodo', email)
    if not token:
        print('Could not find token. Please authenticate with `./gkeeptodo.py login`')
        exit()
    print('Authorization, this may take a while...')
    try:
        keep.resume(email, token)
    except:
        print('Authentication failed. Try to re-authenticate with `./gkeeptodo.py login`')
        exit()


def stats(config: ConfigParser, keep: Keep, dry: bool, verbose: bool):
    print('Collecting metrics')
    Metric.formats = get_formats(config)
    metrics = get_metrics_from_config(config)

    print('--------------------------------')
    for key in metrics:
        metric = metrics[key]
        load_metric_datapoints(keep, metric)
        metric.sort()

        print(f'Keyword: {metric.keyword}')

        tstamp = datetime.now().strftime('%Y%m%d%H%M%S')

        for mode in metric.modes:
            print(f'Statistics in "{mode.value}" mode')
            series = metric.series(mode)

            if not dry:
                fname = f'{metric.keyword}_{mode.value}_{tstamp}.csv'
                write_series_to_csv_file(fname, series)

            if verbose:
                for p in series:
                    print(
                        f'Point "{p.id}": {p.checked} checked, {p.unchecked} unchecked, {p.total} total, completion {round(p.completion*100)}%')
                print('----')

        print('--------------------------------')


def plan(config: ConfigParser, keep: Keep, from_date: str, to_date: str):
    print('Planning TODOs')

    if from_date:
        from_date = date.fromisoformat(from_date)
    else:
        from_date = date.today()

    if to_date:
        to_date = date.fromisoformat(to_date)
    else:
        to_date = date.today()

    if from_date > to_date:
        print('--to-date should be later than --from-date')
        return

    formats = get_formats(config)
    templates = get_templates_from_config(config, formats)

    for key in templates:
        tpl = templates[key]
        print(f'Template {tpl.name}')

        labels = []
        for name in tpl.labels:
            label = keep.findLabel(name)
            if label:
                labels.append(label)

        todos = tpl.generate(from_date, to_date)
        for t in todos:
            print(t.title, t.items, t.labels)
            add_todo(keep, t, labels)

    keep.sync()
    print('----')


argparser = ArgumentParser(
    description='Export Google Keep statistics')
argparser.add_argument('command', type=str, nargs='?',
                       help='Command: login|stats|plan', default='stats')
argparser.add_argument('-e', '--email', type=str, help='Email')
argparser.add_argument('-c', '--config', type=str,
                       default='gkeeptodo.ini', help='Config file path')
argparser.add_argument('-f', '--from-date', type=str,
                       help='From date as YYYY-MM-DD')
argparser.add_argument('-t', '--to-date', type=str,
                       help='To date as YYYY-MM-DD')
argparser.add_argument('-d', '--dry', action='count', default=0,
                       help='Dry run, do not write any files')
argparser.add_argument('-v', '--verbose', action='count', default=0,
                       help='Print verbose output')

args = argparser.parse_args()

config = get_config(args.config)

email = config['user']['email']
if args.email:
    email = args.email

keep = Keep()


def handle_stats():
    resume(keep, email)
    stats(config, keep, args.dry, args.verbose)


def handle_login():
    login(keep, email)


def handle_plan():
    resume(keep, email)
    plan(config, keep, args.from_date, args.to_date)


handlers = {
    'stats': handle_stats,
    'login': handle_login,
    'plan': handle_plan,
}

if not args.command in handlers:
    print(f'Unknown command: {args.command}')
    exit()

handler = handlers[args.command]

handler()
