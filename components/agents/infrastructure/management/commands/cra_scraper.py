import json
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Get Charities info from CRA Advanced Search'

    def handle(self, *args, **options):
        page_url = "https://apps.cra-arc.gc.ca/ebci/hacc/srch/pub/advncdSrch"

        try:
            response = requests.get(page_url)
            response.raise_for_status()
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Error fetching data: {e}"))
            return

        soup = BeautifulSoup(response.content, 'html.parser')

        # Directly search for the <main> element
        main_element = soup.find('main', class_='col-md-9 col-md-push-3')
        if not main_element:
            self.stdout.write(self.style.ERROR("No <main> element found on the page."))
            return

        # Attempt to find the table within the main element with updated class
        table = main_element.find('table', class_='table table-bordered wb-tables table-striped')
        if not table:
            self.stdout.write(self.style.ERROR("No table found within the main element."))
            return

        # Initialize a list to store extracted data
        data = []

        # Find all <tr> elements in the table
        rows = table.find_all('tr')
        if not rows:
            self.stdout.write(self.style.ERROR("No rows found in the table."))
            return

        # Iterate over the rows, skipping the header row
        for i, row in enumerate(rows[1:], start=1):  # Skip the first row (headers)
            cols = row.find_all('td')
            if cols and len(cols) >= 6:
                organization_name = cols[0].get_text(strip=True)
                status = cols[1].get_text(strip=True)
                qualified_donee_type = cols[2].get_text(strip=True)
                province_territory = cols[3].get_text(strip=True)
                city = cols[4].get_text(strip=True)
                effective_date = cols[5].get_text(strip=True)

                charity_data = {
                    'Organization Name': organization_name,
                    'Status': status,
                    'Type of Qualified Donee': qualified_donee_type,
                    'Province/Territory': province_territory,
                    'City': city,
                    'Effective Date of Status': effective_date,
                }
                data.append(charity_data)

                # Optionally, limit to first 10 entries
                if i >= 10:
                    break

        if not data:
            self.stdout.write(self.style.ERROR("No data extracted from the table."))
            return

        # Convert the list of charity data to JSON format
        json_data = json.dumps(data, indent=4)

        # Print the JSON data
        self.stdout.write(self.style.SUCCESS("Extracted Charity Data in JSON format:"))
        self.stdout.write(json_data)

        # Optional: Save JSON data to a file
        # with open('charities.json', 'w', encoding='utf-8') as jsonfile:
        #     jsonfile.write(json_data)
        # self.stdout.write(self.style.SUCCESS("Data saved to charities.json"))
