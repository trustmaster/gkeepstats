# Google Keep Stats

Google Keep Task List statistics exporter tool.

Features:

- Calculate overall completion rate for task lists by keyword
- TODO: Export task list completion time series chart, aggregated daily/weekly/monthly/yearly

## Installation

This script requires Python 3 and https://github.com/kiwiz/gkeepapi to run. Install the pre-requisite library via Pip3:

```
pip3 install gkeepapi
```

Optional: make the script executable:

```
chmod +x gkeepstats.py
```

## Usage

This tool is configured via a config file, to avoid reentering parameters on every call. Copy the example config file:

```
cp gkeepstats.example.ini gkeepstats.ini
```

And edit it to come up with your own setup.

Then you can simply call the script in one of the available ways:

```
python3 gkeepstats.py
# or
./gkeepstats.py
```

## Credits

This tool uses the unofficial Google Keep API https://github.com/kiwiz/gkeepapi by [kiwiz](https://github.com/kiwiz). Google Keep is of course a registered trademark of Google and neither the API nor this script are affiliated with Google.
