"""Country of a posting's location, for the map view.

Offline and approximate: a posting's location text is matched against country
names, common alternative names and the cities that postings name most often.
Each country is drawn at its geographic centre. Nothing is sent to a geocoding
service, so members' job lists never leave the server.
"""

import re

# code|latitude|longitude|name|other names...
COUNTRIES = """
AF|33.94|67.71|Afghanistan
AL|41.15|20.17|Albania
DZ|28.03|1.66|Algeria
AD|42.55|1.60|Andorra
AO|-11.20|17.87|Angola
AG|17.06|-61.80|Antigua and Barbuda
AR|-38.42|-63.62|Argentina
AM|40.07|45.04|Armenia
AU|-25.27|133.78|Australia
AT|47.52|14.55|Austria
AZ|40.14|47.58|Azerbaijan
BS|25.03|-77.40|Bahamas
BH|25.93|50.64|Bahrain
BD|23.68|90.36|Bangladesh
BB|13.19|-59.54|Barbados
BY|53.71|27.95|Belarus
BE|50.50|4.47|Belgium
BZ|17.19|-88.50|Belize
BJ|9.31|2.32|Benin
BT|27.51|90.43|Bhutan
BO|-16.29|-63.59|Bolivia
BA|43.92|17.68|Bosnia and Herzegovina|Bosnia
BW|-22.33|24.68|Botswana
BR|-14.24|-51.93|Brazil
BN|4.54|114.73|Brunei|Brunei Darussalam
BG|42.73|25.49|Bulgaria
BF|12.24|-1.56|Burkina Faso|Burkina
BI|-3.37|29.92|Burundi
CV|16.00|-24.01|Cabo Verde|Cape Verde
KH|12.57|104.99|Cambodia
CM|7.37|12.35|Cameroon
CA|56.13|-106.35|Canada
CF|6.61|20.94|Central African Republic|CAR
TD|15.45|18.73|Chad
CL|-35.68|-71.54|Chile
CN|35.86|104.20|China
CO|4.57|-74.30|Colombia
KM|-11.88|43.87|Comoros
CG|-0.23|15.83|Republic of the Congo|Congo|Congo-Brazzaville|Congo (Brazzaville)
CD|-4.04|21.76|Democratic Republic of the Congo|DR Congo|DRC|Democratic Republic of Congo|Congo (Kinshasa)|Congo, The Democratic Republic of the|Congo DR
CR|9.75|-83.75|Costa Rica
CI|7.54|-5.55|Côte d'Ivoire|Cote d'Ivoire|Cote dIvoire|Ivory Coast
HR|45.10|15.20|Croatia
CU|21.52|-77.78|Cuba
CY|35.13|33.43|Cyprus
CZ|49.82|15.47|Czechia|Czech Republic
DK|56.26|9.50|Denmark
DJ|11.83|42.59|Djibouti
DM|15.41|-61.37|Dominica
DO|18.74|-70.16|Dominican Republic
EC|-1.83|-78.18|Ecuador
EG|26.82|30.80|Egypt
SV|13.79|-88.90|El Salvador
GQ|1.65|10.27|Equatorial Guinea
ER|15.18|39.78|Eritrea
EE|58.60|25.01|Estonia
SZ|-26.52|31.47|Eswatini|Swaziland
ET|9.15|40.49|Ethiopia
FJ|-16.58|179.41|Fiji
FI|61.92|25.75|Finland
FR|46.23|2.21|France
GA|-0.80|11.61|Gabon
GM|13.44|-15.31|Gambia|The Gambia
GE|42.32|43.36|Georgia
DE|51.17|10.45|Germany
GH|7.95|-1.02|Ghana
GR|39.07|21.82|Greece
GD|12.26|-61.60|Grenada
GT|15.78|-90.23|Guatemala
GN|9.95|-9.70|Guinea
GW|11.80|-15.18|Guinea-Bissau|Guinea Bissau
GY|4.86|-58.93|Guyana
HT|18.97|-72.29|Haiti
HN|15.20|-86.24|Honduras
HK|22.40|114.11|Hong Kong
HU|47.16|19.50|Hungary
IS|64.96|-19.02|Iceland
IN|20.59|78.96|India
ID|-0.79|113.92|Indonesia
IR|32.43|53.69|Iran|Iran (Islamic Republic of)
IQ|33.22|43.68|Iraq
IE|53.41|-8.24|Ireland
IL|31.05|34.85|Israel
IT|41.87|12.57|Italy
JM|18.11|-77.30|Jamaica
JP|36.20|138.25|Japan
JO|30.59|36.24|Jordan
KZ|48.02|66.92|Kazakhstan
KE|-0.02|37.91|Kenya
KI|-3.37|-168.73|Kiribati
XK|42.60|20.90|Kosovo
KW|29.31|47.48|Kuwait
KG|41.20|74.77|Kyrgyzstan|Kyrgyz Republic
LA|19.86|102.50|Laos|Lao PDR|Lao People's Democratic Republic
LV|56.88|24.60|Latvia
LB|33.85|35.86|Lebanon
LS|-29.61|28.23|Lesotho
LR|6.43|-9.43|Liberia
LY|26.34|17.23|Libya
LI|47.17|9.56|Liechtenstein
LT|55.17|23.88|Lithuania
LU|49.82|6.13|Luxembourg
MG|-18.77|46.87|Madagascar
MW|-13.25|34.30|Malawi
MY|4.21|101.98|Malaysia
MV|3.20|73.22|Maldives
ML|17.57|-4.00|Mali
MT|35.94|14.38|Malta
MH|7.13|171.18|Marshall Islands
MR|21.01|-10.94|Mauritania
MU|-20.35|57.55|Mauritius
MX|23.63|-102.55|Mexico
MD|47.41|28.37|Moldova|Republic of Moldova
MC|43.75|7.41|Monaco
MN|46.86|103.85|Mongolia
ME|42.71|19.37|Montenegro
MA|31.79|-7.09|Morocco
MZ|-18.67|35.53|Mozambique
MM|21.91|95.96|Myanmar|Burma
NA|-22.96|18.49|Namibia
NP|28.39|84.12|Nepal
NL|52.13|5.29|Netherlands|The Netherlands|Holland
NZ|-40.90|174.89|New Zealand
NI|12.87|-85.21|Nicaragua
NE|17.61|8.08|Niger
NG|9.08|8.68|Nigeria
KP|40.34|127.51|North Korea|Democratic People's Republic of Korea|DPRK
MK|41.61|21.75|North Macedonia|Macedonia
NO|60.47|8.47|Norway
OM|21.51|55.92|Oman
PK|30.38|69.35|Pakistan
PS|31.95|35.23|Palestine|State of Palestine|occupied Palestinian territory|West Bank|Gaza|Gaza Strip
PA|8.54|-80.78|Panama
PG|-6.31|143.96|Papua New Guinea
PY|-23.44|-58.44|Paraguay
PE|-9.19|-75.02|Peru
PH|12.88|121.77|Philippines
PL|51.92|19.15|Poland
PT|39.40|-8.22|Portugal
PR|18.22|-66.59|Puerto Rico
QA|25.35|51.18|Qatar
RO|45.94|24.97|Romania
RU|61.52|105.32|Russia|Russian Federation
RW|-1.94|29.87|Rwanda
KN|17.36|-62.78|Saint Kitts and Nevis
LC|13.91|-60.98|Saint Lucia
WS|-13.76|-172.10|Samoa
ST|0.19|6.61|Sao Tome and Principe|São Tomé and Príncipe|Sao Tome
SA|23.89|45.08|Saudi Arabia
SN|14.50|-14.45|Senegal
RS|44.02|21.01|Serbia
SC|-4.68|55.49|Seychelles
SL|8.46|-11.78|Sierra Leone
SG|1.35|103.82|Singapore
SK|48.67|19.70|Slovakia
SI|46.15|15.00|Slovenia
SB|-9.65|160.16|Solomon Islands
SO|5.15|46.20|Somalia|Somaliland|Puntland
ZA|-30.56|22.94|South Africa
KR|35.91|127.77|South Korea|Republic of Korea|Korea
SS|7.31|30.30|South Sudan
ES|40.46|-3.75|Spain
LK|7.87|80.77|Sri Lanka
SD|12.86|30.22|Sudan
SR|3.92|-56.03|Suriname
SE|60.13|18.64|Sweden
CH|46.82|8.23|Switzerland
SY|34.80|39.00|Syria|Syrian Arab Republic
TW|23.70|120.96|Taiwan
TJ|38.86|71.28|Tajikistan
TZ|-6.37|34.89|Tanzania|United Republic of Tanzania
TH|15.87|100.99|Thailand
TL|-8.87|125.73|Timor-Leste|East Timor
TG|8.62|0.82|Togo
TO|-21.18|-175.20|Tonga
TT|10.69|-61.22|Trinidad and Tobago
TN|33.89|9.54|Tunisia
TR|38.96|35.24|Türkiye|Turkey|Turkiye
TM|38.97|59.56|Turkmenistan
UG|1.37|32.29|Uganda
UA|48.38|31.17|Ukraine
AE|23.42|53.85|United Arab Emirates|UAE
GB|55.38|-3.44|United Kingdom|UK|U.K.|Great Britain|England|Scotland|Wales|Northern Ireland
US|37.09|-95.71|United States|USA|U.S.|U.S.A.|United States of America|US
UY|-32.52|-55.77|Uruguay
UZ|41.38|64.59|Uzbekistan
VU|-15.38|166.96|Vanuatu
VE|6.42|-66.59|Venezuela
VN|14.06|108.28|Vietnam|Viet Nam
YE|15.55|48.52|Yemen
ZM|-13.13|27.85|Zambia
ZW|-19.02|29.15|Zimbabwe
"""

# Cities postings often name without their country.
CITIES = {
    "ET": "Addis Ababa|Addis|Hawassa|Bahir Dar|Mekelle|Dire Dawa|Gondar|Jimma|Adama|Gambella|Jijiga|Semera",
    "KE": "Nairobi|Mombasa|Kisumu|Kakuma|Dadaab|Garissa",
    "UG": "Kampala|Entebbe|Gulu|Arua",
    "TZ": "Dar es Salaam|Dodoma|Arusha|Zanzibar",
    "RW": "Kigali",
    "BI": "Bujumbura|Gitega",
    "SS": "Juba",
    "SD": "Khartoum|Port Sudan",
    "SO": "Mogadishu|Hargeisa|Garowe|Baidoa",
    "ER": "Asmara",
    "NG": "Lagos|Abuja|Maiduguri",
    "GH": "Accra|Kumasi|Tamale",
    "SN": "Dakar",
    "ML": "Bamako",
    "NE": "Niamey",
    "BF": "Ouagadougou",
    "CI": "Abidjan",
    "CD": "Kinshasa|Goma|Bukavu|Lubumbashi",
    "CG": "Brazzaville",
    "ZM": "Lusaka",
    "ZW": "Harare|Bulawayo",
    "MW": "Lilongwe|Blantyre",
    "MZ": "Maputo|Beira",
    "MG": "Antananarivo",
    "ZA": "Johannesburg|Pretoria|Cape Town|Durban",
    "BW": "Gaborone",
    "NA": "Windhoek",
    "EG": "Cairo",
    "MA": "Rabat|Casablanca",
    "TN": "Tunis",
    "MR": "Nouakchott",
    "GN": "Conakry",
    "SL": "Freetown",
    "LR": "Monrovia",
    "TG": "Lomé|Lome",
    "BJ": "Cotonou",
    "CM": "Yaoundé|Yaounde|Douala",
    "CF": "Bangui",
    "TD": "N'Djamena|Ndjamena",
    "JO": "Amman",
    "LB": "Beirut",
    "SY": "Damascus",
    "IQ": "Baghdad|Erbil",
    "YE": "Sana'a|Sanaa|Aden",
    "AF": "Kabul",
    "PK": "Islamabad|Karachi|Lahore",
    "BD": "Dhaka|Cox's Bazar",
    "IN": "New Delhi|Delhi|Mumbai|Bangalore|Bengaluru|Hyderabad|Chennai",
    "NP": "Kathmandu",
    "LK": "Colombo",
    "TH": "Bangkok",
    "PH": "Manila",
    "ID": "Jakarta",
    "VN": "Hanoi|Ho Chi Minh City",
    "KH": "Phnom Penh",
    "MM": "Yangon",
    "CN": "Beijing|Shanghai",
    "JP": "Tokyo",
    "CH": "Geneva|Zurich|Bern|Basel|Lausanne",
    "IT": "Rome|Milan|Turin",
    "FR": "Paris|Lyon",
    "GB": "London|Edinburgh|Oxford|Cambridge",
    "DE": "Berlin|Bonn|Munich|Hamburg|Frankfurt",
    "BE": "Brussels",
    "NL": "The Hague|Amsterdam|Rotterdam|Wageningen",
    "DK": "Copenhagen",
    "SE": "Stockholm",
    "NO": "Oslo",
    "AT": "Vienna",
    "ES": "Madrid|Barcelona",
    "PT": "Lisbon",
    "IE": "Dublin",
    "UA": "Kyiv|Kiev",
    "TR": "Istanbul|Ankara|Gaziantep",
    "AE": "Dubai|Abu Dhabi",
    "QA": "Doha",
    "SA": "Riyadh|Jeddah",
    "IR": "Tehran",
    "US": "New York|Washington|Washington DC|San Francisco|Boston|Seattle|Los Angeles|Chicago|Denver|Austin",
    "CA": "Toronto|Ottawa|Montreal|Vancouver",
    "MX": "Mexico City",
    "CO": "Bogotá|Bogota",
    "PE": "Lima",
    "BR": "São Paulo|Sao Paulo|Rio de Janeiro|Brasília|Brasilia",
    "HT": "Port-au-Prince",
    "AU": "Sydney|Melbourne|Canberra|Brisbane",
    "NZ": "Wellington|Auckland",
    "MY": "Kuala Lumpur",
}

REMOTE = re.compile(r"\b(remote|home[- ]based|work from home|anywhere|worldwide)\b", re.I)


def _load():
    places, names = {}, []
    for line in COUNTRIES.strip().splitlines():
        code, lat, lng, name, *other = line.split("|")
        places[code] = {"code": code, "country": name, "lat": float(lat), "lng": float(lng)}
        names += [(n, code) for n in [name, *other]]
    for code, cities in CITIES.items():
        names += [(c, code) for c in cities.split("|")]
    # Longest names first, so "South Sudan" wins over "Sudan" and "Guinea-Bissau" over "Guinea".
    names.sort(key=lambda n: -len(n[0]))
    patterns = []
    for name, code in names:
        # Short capitalised codes (UK, USA, DRC) match only in capitals; names in any case.
        flags = 0 if name.isupper() or "." in name else re.I
        patterns.append((re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", flags), code))
    return places, patterns


PLACES, PATTERNS = _load()


def place(*texts):
    """{code, country, lat, lng} of the first country named in the texts, or None."""
    for text in texts:
        text = str(text or "")
        if not text.strip():
            continue
        found = []
        for pattern, code in PATTERNS:
            m = pattern.search(text)
            if m:
                found.append((m.start(), code))
                text = text[: m.start()] + " " * (m.end() - m.start()) + text[m.end():]
        if found:
            return PLACES[min(found)[1]]
    return None


def is_remote(location):
    return bool(REMOTE.search(str(location or "")))
