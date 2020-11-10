#!/usr/local/bin/python3
from argparse import ArgumentParser
from configparser import ConfigParser
import csv
from datetime import date, datetime
from enum import Enum
import getpass
import keyring
import os
import re

from gkeepapi import Keep


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


def parse_modes(list_str: str) -> list[Mode]:
    items = list_str.split(',')
    modes = [Mode.from_str(s.strip()) for s in items]

    return modes


def id_to_date(formats: dict, id: str) -> date:
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


def get_metrics_from_config(config: ConfigParser) -> dict[str, Metric]:
    metrics = {}
    for s in config.sections():
        if s != 'user' and s != 'formats':
            m = Metric(s, config[s]['keyword'], config[s]['modes'])
            metrics[s] = m
    return metrics


def load_metric_datapoints(keep: Keep, m: Metric) -> Metric:
    notes = keep.find(query=m.keyword)

    for note in notes:
        if not hasattr(note, 'items'):
            continue
        # strip keyword and spaces from title
        id = note.title.removeprefix(m.keyword).removesuffix(m.keyword).strip()
        m.add_data_point(id, len(note.checked), len(note.unchecked))

    return m


def get_config(path='gkeepstats.ini'):
    if not os.path.isfile(path):
        print(f'Config file {path} not found')
        exit()

    ini = ConfigParser()
    ini.read(path)

    return ini


def write_series_to_csv_file(fname: str, series: list[DataPoint]):
    with open(fname, 'w') as csvfile:
        writer = csv.writer(csvfile)
        # Write header
        writer.writerow(
            ['Index', 'Checked', 'Unchecked', 'Total', 'Completion'])
        for p in series:
            writer.writerow(
                [p.id, p.checked, p.unchecked, p.total, p.completion])


argparser = ArgumentParser(
    description='Export Google Keep statistics')
argparser.add_argument('-e', '--email', type=str, help='Email')
argparser.add_argument('-p', '--auth', action='count', default=0,
                       help='Promt for password to authenticate')
argparser.add_argument('-c', '--config', type=str,
                       default='gkeepstats.ini', help='Config file path')
argparser.add_argument('-d', '--dry', action='count', default=0,
                       help='Dry run, do not write any files')
argparser.add_argument('-v', '--verbose', action='count', default=0,
                       help='Print verbose output')

args = argparser.parse_args()

config = get_config(args.config)

email = config['user']['email']
if args.email:
    email = args.email


should_write = not bool(args.dry)

metrics = get_metrics_from_config(config)

keep = Keep()

if args.auth:
    password = getpass.getpass('Password: ')
    print('Authenticating, this may take a while...')
    try:
        keep.login(config['user']['email'], password)
    except:
        print('Authentication failed')
        exit()

    # Save the auth token in keyring
    token = keep.getMasterToken()
    keyring.set_password('gkeepstats', email, token)

else:
    print('Trying to load access token from keyring')
    token = keyring.get_password('gkeepstats', email)
    if not token:
        print('Could not find token. Try to re-run the command with --auth to save access token in keyring')
        exit()
    print('Authorization, this may take a while...')
    try:
        keep.resume(email, token)
    except:
        print('Authentication failed. Try to reauthenticate with --auth option')
        exit()


print('Collecting metrics')
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

        csvfile = None
        if should_write:
            fname = f'{metric.keyword}_{mode.value}_{tstamp}.csv'
            write_series_to_csv_file(fname, series)

        if args.verbose:
            for p in series:
                print(
                    f'Point "{p.id}": {p.checked} checked, {p.unchecked} unchecked, {p.total} total, completion {round(p.completion*100)}%')
            print('----')

    print('--------------------------------')
