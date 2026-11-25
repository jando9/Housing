import requests
from bs4 import BeautifulSoup

suburb = "riccarton"  # Example suburb, you can change this to any suburb you want to scrape
bedrooms_min = 2  # Minimum number of bedrooms
price_min = 500000  # Minimum price
price_max = 1000000  # Maximum price
property_type = "house"  # Property type (e.g., house, apartment, townhouse)
bathrooms_min = 2  # Minimum number of bathrooms

url = f"https://www.trademe.co.nz/a/property/residential/sale/canterbury/christchurch-city/{suburb}/search?bedrooms_min={bedrooms_min}&price_min={price_min}&price_max={price_max}&property_type={property_type}&bathrooms_min={bathrooms_min}"

key_url = "https://www.google.com/ccm/collect?rcb=9&frm=0&apvc=1&ae=g&auid=107114167.1790897019&dt=Addington%20Homes%20%26%20Real%20Estate%20For%20Sale%20%7C%20Trade%20Me%20Property&en=page_view&dl=https%3A%2F%2Fwww.trademe.co.nz%2Fa%2Fproperty%2Fresidential%2Fsale%2Fcanterbury%2Fchristchurch-city%2Faddington%2Fsearch%3Fbedrooms_min%3D2%26price_min%3D300000%26price_max%3D600000%26property_type%3Dhouse%26bathrooms_min%3D1&scrsrc=www.googletagmanager.com&rnd=668422754.1791953786&navt=r&npa=0&ep.ads_data_redaction=0&gtm=45He6ac1v76796799za200zd76796799xeaxf1&gcd=13l3l3l3l1l1&dma=0&tag_exp=100940059~115938465~115938468~117227716~118897920~118897930~120385422~120469145~120469153~121246026~121246034&tft=1791953786138&tfd=3200&fmt=8"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
response = requests.get(key_url, headers=headers, timeout=10)
data=response.json()
print(data.keys())

soup = BeautifulSoup(response.text, "html.parser")
