"""Country / region detection for job locations.

Location strings from career sites are messy ("Luanda, AO", "Cabinda Province",
"Offshore West Africa", "Al Khobar, Eastern Province"). We match against a
table of country names plus city and alias hints.
"""
import re
import unicodedata

# region -> {canonical country: [aliases and major oil/gas cities]}
COUNTRIES = {
    "GCC": {
        "Saudi Arabia": ["saudi", "ksa", "riyadh", "jeddah", "dhahran", "al khobar", "khobar",
                         "dammam", "jubail", "yanbu", "ras tanura", "aramco", "neom",
                         "eastern province", "jazan", "haradh", "shaybah", " sa,", "(sa)"],
        "United Arab Emirates": ["uae", "u.a.e", "emirates", "abu dhabi", "abudhabi", "dubai",
                                 "sharjah", "ruwais", "musaffah", "al ain", "fujairah",
                                 "ras al khaimah", "jebel ali", "adnoc", " ae,", "(ae)"],
        "Qatar": ["qatar", "doha", "ras laffan", "mesaieed", "dukhan", "lusail", " qa,", "(qa)"],
        "Kuwait": ["kuwait", "ahmadi", "al ahmadi", "shuaiba", "burgan", " kw,", "(kw)"],
        "Oman": ["oman", "muscat", "sohar", "salalah", "duqm", "nizwa", "fahud", "ghala",
                 " om,", "(om)"],
        "Bahrain": ["bahrain", "manama", "sitra", "riffa", " bh,", "(bh)"],
    },
    "Middle East": {
        "Iraq": ["iraq", "iraqi", "baghdad", "basra", "basrah", "erbil", "arbil",
                 "sulaymaniyah", "duhok", "dohuk", "kurdistan", "kirkuk", "mosul",
                 "rumaila", "zubair", "majnoon", "west qurna", "halfaya", "gharraf",
                 "faihaa", "khor al zubair", "umm qasr", " iq,", "(iq)"],
        "Yemen": ["yemen", "sanaa", "aden", "mukalla", " ye,", "(ye)"],
        "Jordan": ["jordan", "amman", "aqaba", " jo,", "(jo)"],
    },
    "Africa": {
        "Angola": ["angola", "luanda", "cabinda", "soyo", "lobito", "benguela", "malongo",
                   " ao,", "(ao)"],
        "Mozambique": ["mozambique", "mocambique", "maputo", "pemba", "palma", "afungi",
                       "cabo delgado", "beira", "nacala", " mz,", "(mz)"],
        "Uganda": ["uganda", "kampala", "hoima", "buliisa", "kabaale", "tilenga", "kingfisher",
                   "entebbe", " ug,", "(ug)"],
        "Nigeria": ["nigeria", "lagos", "port harcourt", "portharcourt", "abuja", "warri",
                    "bonny", "onne", "escravos", "eket", "calabar", " ng,", "(ng)"],
        "Ghana": ["ghana", "accra", "takoradi", "tema", "sekondi", " gh,", "(gh)"],
        "Tanzania": ["tanzania", "dar es salaam", "dodoma", "mtwara", "tanga", " tz,", "(tz)"],
        "Kenya": ["kenya", "nairobi", "mombasa", "lokichar", "turkana", " ke,", "(ke)"],
        "Egypt": ["egypt", "cairo", "alexandria", "suez", "ras shukheir", "damietta",
                  "zohr", "new cairo", " eg,", "(eg)"],
        "Libya": ["libya", "tripoli", "benghazi", "misrata", "sirte", "mellitah", " ly,", "(ly)"],
        "Algeria": ["algeria", "algiers", "alger", "hassi messaoud", "hassi r'mel", "arzew",
                    "oran", "in amenas", " dz,", "(dz)"],
        # Bare "Congo" resolves to the Republic; detect() demotes it when the
        # text actually names the DRC.
        "Congo (Republic)": ["congo", "republic of congo", "congo-brazzaville",
                             "brazzaville", "pointe noire", "pointe-noire",
                             "djeno", "moho", "nkossa", " cg,", "(cg)"],
        "DR Congo": ["democratic republic of congo", "dr congo", "drc", "d.r. congo",
                     "congo-kinshasa", "kinshasa", "lubumbashi", "katanga",
                     " cd,", "(cd)"],
        "Gabon": ["gabon", "libreville", "port gentil", "port-gentil", "gamba", " ga,", "(ga)"],
        "Equatorial Guinea": ["equatorial guinea", "malabo", "bata", "punta europa",
                              " gq,", "(gq)"],
        "Cameroon": ["cameroon", "cameroun", "douala", "yaounde", "limbe", "kribi",
                     " cm,", "(cm)"],
        "Ivory Coast": ["ivory coast", "cote d'ivoire", "côte d'ivoire", "abidjan",
                        "yamoussoukro", " ci,", "(ci)"],
        "Senegal": ["senegal", "dakar", "saint louis", "sangomar", " sn,", "(sn)"],
        "Mauritania": ["mauritania", "nouakchott", "nouadhibou", " mr,", "(mr)"],
        "Namibia": ["namibia", "windhoek", "walvis bay", "luderitz", " na,", "(na)"],
        "South Africa": ["south africa", "johannesburg", "cape town", "durban", "sasolburg",
                         "secunda", "pretoria", " za,", "(za)"],
        "South Sudan": ["south sudan", "juba", "paloch", "bentiu", " ss,", "(ss)"],
        "Sudan": ["sudan", "khartoum", "port sudan"],
        "Chad": ["chad", "n'djamena", "ndjamena", "doba", " td,", "(td)"],
        "Niger": ["niger", "niamey", "agadem", "zinder", " ne,", "(ne)"],
        "Tunisia": ["tunisia", "tunis", "sfax", "gabes", " tn,", "(tn)"],
        "Morocco": ["morocco", "casablanca", "rabat", "tangier", "mohammedia", " ma,", "(ma)"],
        "Ethiopia": ["ethiopia", "addis ababa", " et,", "(et)"],
        "Zambia": ["zambia", "lusaka", "kitwe", " zm,", "(zm)"],
        "Zimbabwe": ["zimbabwe", "harare", "muzarabani", " zw,", "(zw)"],
        "Botswana": ["botswana", "gaborone", " bw,", "(bw)"],
        "Guinea": ["guinea", "conakry", "boke"],
        "Madagascar": ["madagascar", "antananarivo", "tamatave"],
        "Somalia": ["somalia", "mogadishu", "hargeisa"],
        "Rwanda": ["rwanda", "kigali"],
        "Malawi": ["malawi", "lilongwe", "blantyre"],
    },
}

# Phrases that imply the target regions without naming a country.
REGION_HINTS = {
    "GCC": ["gcc", "arabian gulf", "persian gulf", "middle east", "mena", "gulf region"],
    "Africa": ["west africa", "east africa", "north africa", "sub-saharan", "subsaharan",
               "sub saharan", "central africa", "southern africa", "africa"],
}

REMOTE_HINTS = ["remote", "work from home", "telecommute", "work from anywhere", "home based"]

# Not targets - used to spot adverts that are clearly somewhere else, so a
# "remote" advert based in Houston does not sneak through on the remote flag.
NON_TARGET = [
    "united states", "usa", " u.s.", "houston", "texas", "oklahoma", "louisiana",
    "canada", "calgary", "alberta", "bonnyville",
    "united kingdom", "london", "aberdeen", "norwich",
    "netherlands", "amsterdam", "the hague", "rotterdam",
    "norway", "stavanger", "oslo", "france", "paris", "pau",
    "italy", "milan", "rome", "germany", "spain", "madrid",
    "india", "bangalore", "bengaluru", "mumbai", "chennai", "pune", "hyderabad",
    "malaysia", "kuala lumpur", "singapore", "china", "beijing", "shanghai",
    "japan", "tokyo", "korea", "seoul", "australia", "perth", "brisbane",
    "brazil", "rio de janeiro", "sao paulo", "argentina", "mexico", "guyana",
    "trinidad", "kazakhstan", "atyrau", "aktau", "azerbaijan", "baku",
    "russia", "moscow", "turkey", "istanbul", "romania", "poland", "philippines",
    "manila", "indonesia", "jakarta", "vietnam", "thailand", "bangkok",
]
ROTATION_HINTS = ["rotation", "rotational", "fifo", "28/28", "28x28", "14/14", "35/35",
                  "4/4", "6/3", "8/2", "offshore", "swing", "residential", "expat"]


def _norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def _pad(s):
    """Pad so aliases anchored on punctuation (' sa,') still match at the edges.
    Separators such as '/' are left intact: they are already non-alphanumeric,
    so the word-boundary lookarounds treat them as breaks, and rotation
    patterns like '28/28' survive."""
    return " " + s + " ,"


def _word(needle, haystack):
    """Whole-word containment. Alphanumeric boundaries only, so aliases that
    end in punctuation (' ng,', '(ao)') still match."""
    return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(needle), haystack) is not None


def detect(*texts):
    """Return (countries, regions, flags) found across the supplied strings."""
    blob = _pad(_norm(" , ".join([t for t in texts if t])))
    countries, regions = [], []
    for region, table in COUNTRIES.items():
        for country, aliases in table.items():
            needles = [_norm(country)] + [_norm(a) for a in aliases]
            for n in needles:
                if not n:
                    continue
                # Always match on word boundaries. Substring matching gave false
                # positives such as Bonnyville (Canada) hitting Bonny (Nigeria).
                if _word(n, blob):
                    if country not in countries:
                        countries.append(country)
                    if region not in regions:
                        regions.append(region)
                    break
    for region, hints in REGION_HINTS.items():
        for h in hints:
            if _word(_norm(h), blob):
                if region not in regions:
                    regions.append(region)
                break

    # "Kinshasa, DR Congo" also contains the word "congo", which would otherwise
    # tag the job as Republic of the Congo as well. The DRC evidence is more
    # specific, so it wins.
    if "DR Congo" in countries and "Congo (Republic)" in countries:
        countries.remove("Congo (Republic)")

    flags = []
    if any(_word(_norm(h), blob) for h in REMOTE_HINTS):
        flags.append("remote")
    if any(_word(_norm(h), blob) for h in ROTATION_HINTS):
        flags.append("rotational")
    return countries, regions, flags


def detect_other(*texts):
    """True when the text clearly points at a country outside our targets."""
    blob = _pad(_norm(" , ".join([t for t in texts if t])))
    return any(_word(_norm(h), blob) for h in NON_TARGET)


def all_countries():
    out = []
    for table in COUNTRIES.values():
        out.extend(table.keys())
    return sorted(out)
