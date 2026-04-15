import requests
from bs4 import BeautifulSoup


class TenderScanner:

    def __init__(self):
        self.sources = [
            "https://goszakup.gov.kz",
            "https://zakup.sk.kz"
        ]

    def scan(self):
        tenders = []

        for source in self.sources:
            try:
                response = requests.get(source, timeout=10)

                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    tenders.append({
                        "source": source,
                        "status": "available",
                        "items_found": len(soup.find_all("a"))
                    })

                else:
                    tenders.append({
                        "source": source,
                        "status": "error"
                    })

            except Exception as e:
                tenders.append({
                    "source": source,
                    "status": "failed",
                    "error": str(e)
                


scanner = TenderScanner()


if __name__ == "__main__":
    results = scanner.scan()

    for r in results:
        print(r)