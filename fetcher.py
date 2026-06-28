import requests # the library for fetching things over the internet

# The SEC requires you to identify yourself. Put your real name + email here.
HEADERS = {"User-Agent": "John Fu johnfu090402@gmail.com"}


# Pick a recent WEEKDAY. Format is YYYYMMDD. Change this to a recent date.
def get_form4_paths(date, quarter):
    """Return a list of Form 4 filing paths for one day.
    date: 'YYYYMMDD' string. quarter: 'QTR1'..'QTR4'.
    """
    year = date[:4]

    # Build the URL for that day's master index.
    # Note: QTR2 = April-June. Adjust the quarter if your date is in a different one.
    url = f"https://www.sec.gov/Archives/edgar/daily-index/{year}/{quarter}/master.{date}.idx"
    response = requests.get(url, headers=HEADERS) #fetch the file

    if response.status_code != 200: # A status code of 200 means success. Anything else means something went wrong.
        # No index for this day (weekend/holiday) or other problem — return empty.
        return []

    paths = []
    for line in response.text.splitlines(): # The file's text content. Split it into individual lines.
        # Each data line has fields separated by "|". We split on that.
        # Format is: CIK|Company Name|Form Type|Date Filed|Filename
        parts = line.split("|")
        if len(parts) == 5: # A valid data line has exactly 5 parts. The header/junk lines won't.
            cik, company, form_type, date_filed, filename = parts
            if form_type.strip() == "4": # We only care about Form 4 (insider trades).
                paths.append(filename.strip())
    return paths

