import requests
import xml.etree.ElementTree as ET

HEADERS = {"User-Agent": "Your Name your.email@example.com"}

# A real filing path, like: "edgar/data/2034782/0002034782-26-000006.txt"
# function adds a transaction's data onto the database
def parse_filing(filing_path):
    """Download one filing and return a list of ALL its transactions (any code)."""

    # 1. Build the full URL and download the submission file.
    url = "https://www.sec.gov/Archives/" + filing_path
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        return []   # couldn't download it — skip this filing

    full_text = response.text

    # 2. Slice out just the Form 4 XML block (ignore the wrapper around it).
    start = full_text.find("<ownershipDocument>")
    end = full_text.find("</ownershipDocument>")
    if start == -1 or end == -1:
        return []
    xml_string = full_text[start:end + len("</ownershipDocument>")]

    # 3. Parse the XML; skip the filing if it's malformed.
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return []

    # 4. Pull the filing-wide fields (same for every transaction in the filing).
    company = root.findtext("issuer/issuerName")
    ticker  = root.findtext("issuer/issuerTradingSymbol")
    insider = root.findtext("reportingOwner/reportingOwnerId/rptOwnerName")
    role    = root.findtext("reportingOwner/reportingOwnerRelationship/officerTitle")
    accession = filing_path.split("/")[-1].replace(".txt", "") # The accession number (the filing's unique SEC ID) lives in the filename.

    # 5. Loop the transactions; keep ALL types and record each code.
    transactions = []
    for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = txn.findtext("transactionCoding/transactionCode")
        shares_text = txn.findtext("transactionAmounts/transactionShares/value")
        price_text  = txn.findtext("transactionAmounts/transactionPricePerShare/value")

        # only adding insider purchases and ignoring other actions (selling, scheduled purchaes...)
        # the code is "P", Doing this because I tried fetching every single transaction and it takes too long + too many data entries
        # only purchases are necessary for now. Subject to change later
        if code == "P":
            transactions.append({
                "accession": accession,
                "company": company,
                "ticker": ticker,
                "insider": insider,
                "role": role,
                "code": code,                                       # P, S, A, G, M, ...
                "shares": float(shares_text),
                # Gifts/grants can have no price — store 0.0 rather than crashing.
                "price": float(price_text) if price_text else 0.0,
                "date": txn.findtext("transactionDate/value"),
            })

    return transactions