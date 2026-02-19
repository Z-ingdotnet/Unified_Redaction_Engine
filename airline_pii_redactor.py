import re
import logging
import json
from datetime import datetime
from dateutil import parser
from pathlib import Path

# Try to import optional dependencies
try:
    import hanlp
    HANLP_AVAILABLE = True
except ImportError:
    HANLP_AVAILABLE = False

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Suppress Presidio warnings
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

class InternationalPhoneRecognizer:
    """
    Custom phone number recognizer for international formats.
    """
    PHONE_PATTERNS = {
        'CN': {'pattern': r'(?<![0-9])1[3-9][0-9]{9}(?![0-9])', 'min_length': 11, 'max_length': 11, 'prefix_validator': lambda x: x[:3] in {'130','131','132','133','134','135','136','137','138','139','145','147','149','150','151','152','153','155','156','157','158','159','165','166','170','171','173','175','176','177','178','180','181','182','183','184','185','186','187','188','189','190','191','192','193','195','196','197','198','199'}, 'confidence': 0.95},
        'HK': {'pattern': r'(?<![0-9])(?:\+?852[-\s]?)?[569][0-9]{3}[-\s]?[0-9]{4}(?![0-9])', 'min_length': 8, 'max_length': 12, 'prefix_validator': None, 'confidence': 0.90},
        'TW': {'pattern': r'(?<![0-9])(?:\+?886[-\s]?)?0?9[0-9]{2}[-\s]?[0-9]{3}[-\s]?[0-9]{3}(?![0-9])', 'min_length': 9, 'max_length': 15, 'prefix_validator': None, 'confidence': 0.90},
        'US_CA': {'pattern': r'(?<![0-9])(?:\+?1[-\s]?)?\(?[2-9][0-9]{2}\)?[-\s]?[2-9][0-9]{2}[-\s]?[0-9]{4}(?![0-9])', 'min_length': 10, 'max_length': 16, 'prefix_validator': None, 'confidence': 0.85},
        'UK': {'pattern': r'(?<![0-9])(?:\+?44[-\s]?)?0?7[0-9]{3}[-\s]?[0-9]{6}(?![0-9])', 'min_length': 10, 'max_length': 15, 'prefix_validator': None, 'confidence': 0.85},
        'SG': {'pattern': r'(?<![0-9])(?:\+?65[-\s]?)?[689][0-9]{3}[-\s]?[0-9]{4}(?![0-9])', 'min_length': 8, 'max_length': 12, 'prefix_validator': None, 'confidence': 0.85},
        'MY': {'pattern': r'(?<![0-9])(?:\+?60[-\s]?)?1[0-9]{1}[-\s]?[0-9]{3,4}[-\s]?[0-9]{4}(?![0-9])', 'min_length': 9, 'max_length': 12, 'prefix_validator': None, 'confidence': 0.85},
        'AU': {'pattern': r'(?<![0-9])(?:\+?61[-\s]?)?0?4[0-9]{2}[-\s]?[0-9]{3}[-\s]?[0-9]{3}(?![0-9])', 'min_length': 9, 'max_length': 12, 'prefix_validator': None, 'confidence': 0.85},
        'NZ': {'pattern': r'(?<![0-9])(?:\+?64[-\s]?)?0?2[0-9]{1}[-\s]?[0-9]{3}[-\s]?[0-9]{4}(?![0-9])', 'min_length': 9, 'max_length': 12, 'prefix_validator': None, 'confidence': 0.85},
        'JP': {'pattern': r'(?<![0-9])(?:\+?81[-\s]?)?0?(?:70|80|90)[-\s]?[0-9]{4}[-\s]?[0-9]{4}(?![0-9])', 'min_length': 10, 'max_length': 13, 'prefix_validator': None, 'confidence': 0.85},
        'KR': {'pattern': r'(?<![0-9])(?:\+?82[-\s]?)?0?1[0-9][-\s]?[0-9]{3,4}[-\s]?[0-9]{4}(?![0-9])', 'min_length': 10, 'max_length': 13, 'prefix_validator': None, 'confidence': 0.85},
        'IN': {'pattern': r'(?<![0-9])(?:\+?91[-\s]?)?[6-9][0-9]{4}[-\s]?[0-9]{5}(?![0-9])', 'min_length': 10, 'max_length': 12, 'prefix_validator': None, 'confidence': 0.85}
    }

    def analyze(self, text):
        results = []
        for region, config in self.PHONE_PATTERNS.items():
            for match in re.finditer(config['pattern'], text):
                raw_match = match.group()
                clean_num = re.sub(r'[\s\-\+\(\)]', '', raw_match)
                if not (config['min_length'] <= len(clean_num) <= config['max_length']): continue
                if config['prefix_validator'] and not config['prefix_validator'](clean_num): continue
                results.append({
                    'text': raw_match, 
                    'start': match.start(), 
                    'end': match.end(), 
                    'type': 'PHONE_NUMBER', 
                    'score': config['confidence'], 
                    'region': region
                })
        return results

class SurnameManager:
    """Manager for Romanized Chinese Surnames with Blacklist filtering"""
    def __init__(self):
        # 1. Single Character Surnames
        self.single_surnames = {
            "bai", "ban", "bao", "bei", "bi", "bian", "biao", "bie", "bin", "bing", "bo", "bu",
            "cai", "cao", "cen", "chai", "chan", "chang", "chao", "che", "chen", "cheng", "chi",
            "chong", "chou", "chu", "chuan", "chuang", "chun", "ci", "cong", "cui", "cun", "cuo",
            "da", "dai", "dan", "dang", "dao", "de", "deng", "di", "dian", "diao", "ding", "diu",
            "dong", "dou", "du", "duan", "dun", "duo", "e", "en", "er", "fa", "fan", "fang",
            "fei", "fen", "feng", "fo", "fou", "fu", "ga", "gai", "gan", "gang", "gao", "ge",
            "gei", "gen", "geng", "gong", "gou", "gu", "gua", "guai", "guan", "guang", "gui",
            "gun", "guo", "ha", "hai", "han", "hang", "hao", "he", "hei", "hen", "heng", "hong",
            "hou", "hu", "hua", "huai", "huan", "huang", "hui", "hun", "huo", "ji", "jia", "jian",
            "jiang", "jiao", "jie", "jin", "jing", "jiong", "jiu", "ju", "juan", "jue", "jun",
            "ka", "kai", "kan", "kang", "kao", "ke", "ken", "keng", "kong", "kou", "ku", "kua",
            "kuai", "kuan", "kuang", "kui", "kun", "kuo", "la", "lai", "lan", "lang", "lao", "le",
            "lei", "leng", "li", "lia", "lian", "liang", "liao", "lie", "lin", "ling", "liu",
            "long", "lou", "lu", "luan", "lun", "luo", "ma", "mai", "man", "mang", "mao", "me",
            "mei", "men", "meng", "mi", "mian", "miao", "mie", "min", "ming", "miu", "mo", "mou",
            "mu", "na", "nai", "nan", "nang", "nao", "ne", "nei", "nen", "neng", "ni", "nian",
            "niang", "niao", "nie", "nin", "ning", "niu", "nong", "nu", "nuan", "o", "ou", "pa",
            "pai", "pan", "pang", "pao", "pei", "pen", "peng", "pi", "pian", "piao", "pie", "pin",
            "ping", "po", "pou", "pu", "qi", "qia", "qian", "qiang", "qiao", "qie", "qin", "qing",
            "qiong", "qiu", "qu", "quan", "que", "qun", "ran", "rang", "rao", "re", "ren", "reng",
            "ri", "rong", "rou", "ru", "ruan", "rui", "run", "ruo", "sa", "sai", "san", "sang",
            "sao", "se", "sen", "seng", "sha", "shai", "shan", "shang", "shao", "she", "shen",
            "sheng", "shi", "shou", "shu", "shua", "shuai", "shuan", "shuang", "shui", "shun",
            "shuo", "si", "song", "sou", "su", "suan", "sui", "sun", "suo", "ta", "tai", "tan",
            "tang", "tao", "te", "teng", "ti", "tian", "tiao", "tie", "ting", "tong", "tou", "tu",
            "tuan", "tui", "tun", "tuo", "wa", "wai", "wan", "wang", "wei", "wen", "weng", "wo",
            "wu", "xi", "xia", "xian", "xiang", "xiao", "xie", "xin", "xing", "xiong", "xiu",
            "xu", "xuan", "xue", "xun", "ya", "yan", "yang", "yao", "ye", "yi", "yin", "ying",
            "yo", "yong", "you", "yu", "yuan", "yue", "yun", "za", "zai", "zan", "zang", "zao",
            "ze", "zei", "zen", "zeng", "zha", "zhai", "zhan", "zhang", "zhao", "zhe", "zhen",
            "zheng", "zhi", "zhong", "zhou", "zhu", "zhua", "zhuai", "zhuan", "zhuang", "zhui",
            "zhun", "zhuo", "zi", "zong", "zou", "zu", "zuan", "zui", "zun", "zuo",
            'lee', 'ng', 'yung', 'yee', 'yip', 'teoh', 'tay', 'tham', 'woon', 'chan', 'chiu',
            'chao', 'wong', 'hwang', 'chou', 'shyu', 'hsu', 'suen', 'kwok', 'ho', 'lam', 'lo',
            'cheng', 'tsieh', 'yuen', 'tsang', 'chong', 'chung', 'tsui', 'shek', 'shum', 'cheung',
            'cheong', 'chueng', 'leung', 'leong', 'yeung', 'chau', 'lau', 'kwan', 'kwong', 'yau'
        }

        # 2. Compound Surnames
        self.compound_surnames = {
            'ouyang', 'shangguan', 'sima', 'zhuge', 'ximen', 'beigong', 'gongsun', 'chunyu',
            'dantai', 'dongfang', 'duanmu', 'gongxi', 'gongye', 'guliang', 'guanqiu', 'haan',
            'huangfu', 'jiagu', 'jinyun', 'lanxu', 'liangqiu', 'linghu', 'lvqiu', 'moyao',
            'nangong', 'shusun', 'situ', 'taihu', 'weisheng', 'wuyan', 'xiahou', 'xianyu',
            'xiangsi', 'xueqiu', 'yanshi', 'yuchi', 'zhaoshe', 'zhengxi', 'zhongli', 'zhongsun',
            'zhuanyu', 'zhuansun', 'zongzheng', 'zuifu', 'nalan', 'auyeung', 'szeto'
        }

        # 3. Blacklist (Common words)
        self.blacklist = {
            'change', 'challenge', 'chance', 'channel', 'charge', 'chart', 'chat', 'cheap',
            'check', 'cheese', 'chemical', 'chest', 'chicken', 'chief', 'child', 'china',
            'chinese', 'chocolate', 'choice', 'choose', 'christmas', 'church', 'cinema',
            'admin', 'root', 'user', 'test', 'guest', 'default', 'password', 'username',
            'login', 'logout', 'system', 'server', 'client', 'database', 'email', 'mail',
            'phone', 'mobile', 'contact', 'info', 'information', 'address', 'name', 'id',
            'account', 'profile', 'setting', 'config', 'configuration', 'api', 'interface',
            'example', 'gmail', 'yahoo', 'hotmail', 'qq', '163', '126', 'sina', 'outlook',
            'icloud', 'protonmail', 'foxmail', 'aliyun', 'sohu', 'yeah', 'live', 'msn',
            'this', 'that', 'with', 'from', 'they', 'have', 'were', 'said', 'time', 'than',
            'them', 'into', 'just', 'like', 'over', 'also', 'back', 'only', 'know', 'take',
            'year', 'good', 'some', 'come', 'make', 'well', 'very', 'when', 'much', 'would',
            'there', 'their', 'what', 'about', 'which', 'after', 'first', 'never', 'these',
            'think', 'where', 'being', 'every', 'great', 'might', 'shall', 'while', 'those',
            'before', 'should', 'himself', 'themselves', 'both', 'any', 'each', 'few', 'more',
            'most', 'other', 'some', 'such', 'what', 'which', 'who', 'whom', 'whose', 'why',
            'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some',
            'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very'
        }

    def is_surname(self, word):
        w_lower = word.lower()
        if w_lower in self.blacklist:
            return False
        return (w_lower in self.single_surnames) or (w_lower in self.compound_surnames)

    def detect_names(self, text):
        results = []
        # Heuristic: Look for 2 consecutive Capitalized words where at least one is a surname.
        for match in re.finditer(r'\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b', text):
            word1 = match.group(1)
            word2 = match.group(2)
            if self.is_surname(word1) or self.is_surname(word2):
                results.append({
                    'text': match.group(),
                    'start': match.start(),
                    'end': match.end(),
                    'type': 'PERSON',
                    'score': 0.85
                })

        # Compound Surnames explicitly
        for match in re.finditer(r'\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b', text):
            if match.group(1).lower() in self.compound_surnames:
                 results.append({
                    'text': match.group(),
                    'start': match.start(),
                    'end': match.end(),
                    'type': 'PERSON',
                    'score': 0.9
                })
        return results

class AirlinePIIRedactor:
    def __init__(self):
        # Initialize Presidio Analyzer with explicit model configuration to avoid auto-download issues
        try:
            from presidio_analyzer.nlp_engine import SpacyNlpEngine
            # Try to load large model first, fallback to small if needed
            try:
                import spacy
                if not spacy.util.is_package("en_core_web_lg"):
                    if spacy.util.is_package("en_core_web_sm"):
                        model_name = "en_core_web_sm"
                    else:
                        spacy.cli.download("en_core_web_sm")
                        model_name = "en_core_web_sm"
                else:
                    model_name = "en_core_web_lg"
                
                nlp_engine = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": model_name}])
                self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
            except Exception as e:
                print(f"Warning: Failed to initialize SpacyNlpEngine ({e}). Using default AnalyzerEngine.")
                self.analyzer = AnalyzerEngine()
        except Exception:
             self.analyzer = AnalyzerEngine()

        self.anonymizer = AnonymizerEngine()
        self.phone_recognizer = InternationalPhoneRecognizer()
        self.surname_manager = SurnameManager()
        
        # Initialize HanLP with robust fallback
        self.hanlp_ner = None
        if HANLP_AVAILABLE:
            try:
                # Attempt to load small model
                self.hanlp_ner = hanlp.load(hanlp.pretrained.ner.MSRA_NER_ELECTRA_SMALL_ZH)
            except Exception as e:
                print(f"Warning: HanLP Model load failed ({e}). Using Regex fallback for Chinese names.")

        self._register_custom_recognizers()
        self._configure_anonymizer()

        # PNR Validation Data
        self.pnr_blacklist = {
            "FLIGHT", "TICKET", "BOARD", "SEATS", "CABIN", "PILOT", "STAFF",
            "HOTEL", "EVENT", "FIRST", "CLASS", "TOTAL", "GROUP", "WORLD",
            "HELLO", "THANK", "DELAY", "CLAIM", "ROUTE", "ADULT", "CHILD",
            "PRICE", "TAXES", "CHECK", "VALID", "ISSUE", "EMAIL", "PHONE",
            "OFFER", "POINT", "MILES", "PARTY", "GUEST", "SORRY", "REPLY",
            "ADMIN", "AGENT", "HOURS", "DATES", "TIMES", "MONTH", "YEARS",
            "COACH", "INFANT", "BAGGAGE", "LUGGAGE", "CREW", "STATUS",
            "GATE", "ARRIVAL", "DEPART", "ROUND", "TRIP", "FARES", "CODES",
            "RULES", "TERMS", "APPLY", "ABOUT", "PRESS", "MEDIA", "LOGIN",
            "WHERE", "THERE", "WHICH", "OTHER", "THEIR", "BELOW", "ABOVE",
            "UNDER", "AFTER", "UNTIL", "SINCE", "WHILE", "NEVER", "AGAIN",
            "ENTRY", "EXIT", "AISLE", "MEALS", "SNACK", "DRINK", "WATER",
            "JUICE", "WINES", "BEERS", "SALES", "DEALS", "CARGO", "FLEET",
            "UNION", "TRUST", "VALUE", "SCORE", "LEVEL", "TIERS", "BASIC",
            "SMART", "SUPER", "HAPPY", "ENJOY", "VISIT", "WATCH", "VIDEO",
            "AUDIO", "MUSIC", "MOVIE", "POWER", "LIGHT", "NIGHT", "DAILY",
            "WEEK", "TODAY", "LATER", "EARLY", "QUICK", "SPEED", "SPACE",
            "PLACE", "TOUCH", "SCREEN", "PANEL", "LEVER", "PEDAL", "WHEEL",
            "TIRES", "BRAKE", "GEARS", "WING", "TAIL", "NOSE", "BODY",
            "PAINT", "COLOR", "WHITE", "BLACK", "GREEN", "STYLE", "MODEL",
            "BUILD", "MAKER", "OWNER", "BUYER", "LEASE", "RENT", "HIRE",
            "COSTS", "SPEND", "MONEY", "CASH", "CARD", "DEBIT", "BANKS",
            "LOANS", "RATES", "TAXIS", "TRAIN", "BUSES", "METRO", "FERRY",
            "SHIPS", "BOAT", "CYCLE", "DRIVE", "RIDER", "WALKS", "STEPS",
            "MILE", "METER", "KILO", "GRAMS", "POUND", "OUNCE", "LITER",
            "GALLON", "REFUND", "CANCEL", "UPDATE", "NOTICE", "ALERT",
            "SAFETY", "OXYGEN", "JACKET", "WINDOW", "MIDDLE", "CENTER",
            "GALLEY", "TOILET", "LOUNGE", "ACCESS", "MEMBER", "SILVER",
            "GOLD", "ELITE", "POINTS", "WALLET", "PAYMENT", "AMOUNT",
            "NUMBER", "COUNT", "COST", "RATE", "FARE", "CHARGES", "DUTY",
            "GOODS", "ITEMS", "BAGS", "PLANE", "AIRBUS", "BOEING", "HELPDESK",
            "SUPPORT", "OFFICE", "CENTER", "MOBILE", "APP", "WEB", "SITE",
            "LINK", "CLICK", "CHOOSE", "OPTION", "ACTION", "RESULT", "ERROR",
            "FAULT", "CASE", "FILE", "RECORD", "DATA", "INFO", "QUERY",
            "ASK", "HELP", "FAQ", "HOME", "MAIN", "MENU", "BACK", "NEXT",
            "PREV", "LAST", "DONE", "FINISH", "START", "END", "STOP",
            "OPEN", "CLOSE", "LOCK", "UNLOCK"
        }
        self.pnr_context_keywords = {
            "pnr", "record locator", "booking", "reservation", "confirm", "confirmation",
            "itinerary", "ticket", "locator", "ref", "reference"
        }
        
        # Chinese Surnames for fallback
        self.chinese_surnames = [
            '赵', '钱', '孙', '李', '周', '吴', '郑', '王', '冯', '陈', '褚', '卫', '蒋', '沈', '韩', '杨',
            '朱', '秦', '尤', '许', '何', '吕', '施', '张', '孔', '曹', '严', '华', '金', '魏', '陶', '姜',
            '林', '马', '胡', '高', '梁', '宋', '邓', '叶', '苏', '卢', '罗', '郭', '赖', '谢', '邱', '侯',
            '曾', '黎', '潘', '杜', '邹', '袁', '丁', '蔡', '崔', '薛', '廖', '尹', '段', '雷', '范', '汪',
            '陳', '黃', '張', '劉', '吳', '鄭', '蔣', '鄧', '葉', '蘇', '盧', '羅', '賴', '謝', '鍾',
            '馮', '馬', '楊', '梁', '宋', '許', '蕭', '龔', '譚',
            '欧阳', '太史', '端木', '上官', '司马', '东方', '独孤', '南宫', '万俟', '闻人', '夏侯', '诸葛', '尉迟', '公羊',
            '歐陽', '司馬', '東方', '獨孤', '南宮', '萬俟', '聞人', '諸葛', '尉遲'
        ]

    def _register_custom_recognizers(self):
        # Airline Patterns
        airline_patterns = {
            # Flight Number: 2 chars (letters/digits) + 3-4 digits. 
            # Give higher score (0.6) to prioritize over PNR (0.4)
            "Flight Number": (r"\b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?\d{3,4}\b", 0.6),
            
            # PNR: 5-6 alphanumeric. 
            # Note: This overlaps with Flight Numbers (e.g. MU567 is 5 chars).
            # We rely on the lower score (0.4) and the PNR validator to filter out Flight Numbers if needed.
            "PNR": (r"\b[A-Z0-9]{5,6}\b", 0.4),
            
            "Ticket Number": (r"\b\d{3}[-]?\d{10}\b", 0.6),
            "Frequent Flyer": (r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{5,12}\b", 0.5) 
        }

        for entity_label, (pattern_regex, score) in airline_patterns.items():
            pattern = Pattern(name=entity_label, regex=pattern_regex, score=score)
            recognizer = PatternRecognizer(supported_entity=entity_label, patterns=[pattern])
            self.analyzer.registry.add_recognizer(recognizer)

    def _configure_anonymizer(self):
        self.anonymizer_operators = {
            "PERSON": OperatorConfig("replace", {"new_value": "[NAME]"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[Phone]"}),
            "DATE_TIME": OperatorConfig("replace", {"new_value": "[DOB]"}), # Only DOBs are kept as DATE_TIME in final results
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[Email]"}),
            "US_BANK_NUMBER": OperatorConfig("replace", {"new_value": "[Payment]"}),
            "UK_NHS": OperatorConfig("replace", {"new_value": "[ID]"}),
            "US_DRIVER_LICENSE": OperatorConfig("replace", {"new_value": "[ID]"}),
            "PNR": OperatorConfig("replace", {"new_value": "[PNR]"}),
            "Flight Number": OperatorConfig("replace", {"new_value": "[Flight no]"}),
            "Ticket Number": OperatorConfig("replace", {"new_value": "[Ticket no]"}),
            "Frequent Flyer": OperatorConfig("replace", {"new_value": "[Frequent Flyer]"}),
            "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[Payment]"})
        }

    def _get_hanlp_entities(self, text):
        if self.hanlp_ner is None:
            return []
        try:
            tokens = list(text)
            entities = self.hanlp_ner(tokens)
            results = []
            for item in entities:
                if len(item) >= 4:
                    entity_text, label, start, end = item[0], item[1], item[2], item[3]
                    if label in ['NR', 'PERSON', 'PER']:
                        results.append({'text': entity_text, 'start': start, 'end': end, 'type': label})
            return results
        except Exception as e:
            # print(f"HanLP runtime error: {e}")
            return []

    def _get_custom_chinese_names(self, text):
        if not hasattr(self, '_chinese_name_pattern'):
            # Rebuild surname list to be absolutely sure
            surnames = self.chinese_surnames
            
            # Explicitly add Traditional chars if missing
            trad_additions = ['陳', '黃', '張', '劉', '吳', '鄭', '蔣', '鄧', '葉', '蘇', '盧', '羅', '賴', '謝', '鍾']
            for s in trad_additions:
                if s not in surnames:
                    surnames.append(s)
            
            # Escape regex special chars just in case (none in Chinese usually but good practice)
            # Join with OR
            surnames_pattern = '|'.join(map(re.escape, sorted(surnames, key=len, reverse=True)))
            
            # Use broad range \u2e80-\u9fff to catch all CJK variations (Simp/Trad/Radicals)
            self._chinese_name_pattern = re.compile(f'({surnames_pattern})[\u2e80-\u9fff]{{1,2}}')
        
        results = []
        for match in self._chinese_name_pattern.finditer(text):
             results.append({
                'text': match.group(),
                'start': match.start(),
                'end': match.end(),
                'type': 'REGEX_NAME'
            })
        return results

    def is_valid_pnr(self, text, entity_text, start, end):
        if entity_text.upper() in self.pnr_blacklist:
            return False
        if entity_text.isalpha() and not entity_text.isupper():
            # "Booking" matches 6 chars but mixed case usually not PNR in this context unless explicit
            return False
        if any(ch.isdigit() for ch in entity_text):
            return True
        # If all alpha and uppercase, check context
        window = 30
        left = max(0, start - window)
        right = min(len(text), end + window)
        snippet = text[left:right].lower()
        return any(k in snippet for k in self.pnr_context_keywords)

    def is_valid_flight_number(self, text):
        # Text should match regex but we need to verify case
        # Regex: \b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?\d{3,4}\b
        # If match was found case-insensitively, 'is 176' matches.
        # We want to ensure the prefix is UPPERCASE.
        parts = text.split()
        if not parts: return False
        prefix = parts[0]
        if len(prefix) > 2 and prefix[-1].isdigit(): # e.g. "is" "176" -> parts ["is", "176"]
             # If split by space
             pass
        
        # Simpler: The whole string should be uppercase (excluding spaces)
        # But '176' is digits. 'is' is letters.
        # Check if any alphabetic char is lowercase
        if any(c.islower() for c in text):
            return False
        return True

    def is_valid_frequent_flyer(self, text):
        # Should be alphanumeric, uppercase.
        if any(c.islower() for c in text):
            return False
        # Should look like a code, not just digits (unless it's a known format, but all digits overlaps with phone/ticket)
        # If all digits, length should be specific?
        # Let's reject all-digit FF numbers to avoid conflict with Phone/Ticket, unless we have strong context (which we check in redact loop)
        if text.isdigit():
            return False
        return True

    def is_likely_dob(self, date_text):
        try:
            # Handle compact dates like 01011990
            if re.fullmatch(r'\d{8}', date_text):
                try:
                    # Try MMDDYYYY first
                    dt = datetime.strptime(date_text, "%m%d%Y")
                except ValueError:
                    try:
                        # Try DDMMYYYY
                        dt = datetime.strptime(date_text, "%d%m%Y")
                    except ValueError:
                        try:
                            # Try YYYYMMDD
                            dt = datetime.strptime(date_text, "%Y%m%d")
                        except ValueError:
                            return False
            else:
                clean_text = re.sub(r'\s+', ' ', date_text).strip()
                dt = parser.parse(clean_text, fuzzy=True)

            current_year = datetime.now().year
            
            # Simple heuristic first:
            if dt.year > current_year:
                return False # Future dates are flight dates
            
            # If date is within last 2 years, it's ambiguous.
            # Assume Flight Date unless proven otherwise (infant DOBs are rare in this context without explicit "infant" tag)
            if current_year - dt.year <= 2:
                return False
                
            if 1900 < dt.year <= current_year - 2:
                return True
            return False
        except:
            return False

    def redact(self, text):
        # Pre-process: Handle brackets or odd formatting that might confuse NLP
        # ... (Same as before)
        
        # 1. Standard Presidio
        results = self.analyzer.analyze(text=text, language='en', score_threshold=0.4)

        # 2. International Phone Recognizer
        phone_results_raw = self.phone_recognizer.analyze(text)
        phone_results = [RecognizerResult('PHONE_NUMBER', p['start'], p['end'], p['score']) for p in phone_results_raw]

        # 3. Chinese Entities
        chinese_results = []
        hanlp_raw = self._get_hanlp_entities(text)
        custom_raw = self._get_custom_chinese_names(text)
        
        # Filter English matches from HanLP to avoid conflict
        hanlp_entities = [e for e in hanlp_raw if not re.search(r'[a-zA-Z]', e['text'])]
        
        # Combine HanLP and Custom Regex
        for entity in hanlp_entities + custom_raw:
            # Check if this Chinese entity overlaps with something Presidio found (rare but possible)
            # Or if it's just a common word (False Positive Prevention)
            # For now, trust the regex/HanLP but maybe add blacklist?
            # Custom Regex returns type 'REGEX_NAME' or 'PERSON' from HanLP.
            # Give high confidence to regex matches for now as they are specific to surname list.
            # Score 0.9 to override Presidio's NRP (0.85) if they conflict (e.g. for "黃小明")
            chinese_results.append(RecognizerResult('PERSON', entity['start'], entity['end'], 0.9))

        # 4. Romanized Names
        romanized_results = []
        romanized_raw = self.surname_manager.detect_names(text)
        for r in romanized_raw:
            romanized_results.append(RecognizerResult('PERSON', r['start'], r['end'], r['score']))

        # 5. Sticky Ticket Numbers (Manual Regex)
        sticky_tickets = []
        for match in re.finditer(r'(?<!\d)\d{13}(?!\d)', text):
             sticky_tickets.append(RecognizerResult('Ticket Number', match.start(), match.end(), 0.9))

        # 6. Combine ALL results
        combined_results = results + phone_results + chinese_results + romanized_results + sticky_tickets

        # DEBUG
        # print(f"DEBUG: Combined results: {len(combined_results)}")
        # for r in combined_results:
        #     print(f"  - {r.entity_type}: {text[r.start:r.end]} (Score: {r.score})")

        # 7. Filter & Refine
        final_results = []
        
        # Helper to check overlaps
        def is_overlap(new_res, existing_list):
            for ex in existing_list:
                if max(new_res.start, ex.start) < min(new_res.end, ex.end):
                    return True
            return False

        # Sort by score/length to prefer better matches? 
        # Actually Presidio Anonymizer handles overlaps (keeps highest score).
        # But we do custom filtering logic that might need clean data.
        
        for res in combined_results:
            entity_text = text[res.start:res.end].strip()

            if res.entity_type == 'DATE_TIME':
                if self.is_likely_dob(entity_text):
                     final_results.append(res)
            
            elif res.entity_type == 'PNR':
                if self.is_valid_pnr(text, entity_text, res.start, res.end):
                    final_results.append(res)
            
            elif res.entity_type == 'Flight Number':
                if self.is_valid_flight_number(entity_text):
                    final_results.append(res)
                
            elif res.entity_type == 'Frequent Flyer':
                if self.is_valid_frequent_flyer(entity_text):
                    # Also require context for FF numbers
                    context_keywords = {'flyer', 'miles', 'points', 'member', 'club', 'program', 'card'}
                    window = 30
                    left = max(0, res.start - window)
                    right = min(len(text), res.end + window)
                    snippet = text[left:right].lower()
                    if any(k in snippet for k in context_keywords):
                         final_results.append(res)
            
            elif res.entity_type == 'PERSON':
                # Filter out single common words that might be false positives from SurnameManager
                # e.g. "May I" -> "May" might be detected if "May" is surname
                if len(entity_text.split()) == 1 and entity_text.lower() in {'may', 'will', 'can', 'long', 'young', 'man', 'king', 'mark', 'rose', 'read', 'book'}:
                    # Only keep if high score or strict context?
                    # SurnameManager usually returns pairs, so single words come from HanLP or Presidio
                    if res.score < 0.6: 
                        continue
                final_results.append(res)

            else:
                final_results.append(res)

        # 8. Anonymize
        try:
            # Add keep operators for non-PII entities
            # We must pass ALL operators including keep ones, or Presidio might default to replace
            # Actually, Presidio Anonymizer defaults to replace with <ENTITY> if no operator is found.
            # So we need to explicitly keep ORGANIZATION, LOCATION, etc. if we want to preserve them.
            
            # Update operators with keep for others
            ops = self.anonymizer_operators.copy()
            ops["ORGANIZATION"] = OperatorConfig("keep")
            ops["LOCATION"] = OperatorConfig("keep")
            ops["GPE"] = OperatorConfig("keep")
            ops["NRP"] = OperatorConfig("keep") # Nationality/Religious/Political
            
            anonymized_result = self.anonymizer.anonymize(text=text, analyzer_results=final_results, operators=ops)
            output_text = anonymized_result.text
            
            # Post-processing normalization
            output_text = self._normalize_output(output_text)
            return output_text
        except Exception as e:
            print(f"Anonymization error: {e}")
            return text

    def _normalize_output(self, text):
        # Ensure spaces around tags: "Hello[NAME]" -> "Hello [NAME]"
        text = re.sub(r'([A-Za-z0-9])(\[)', r'\1 \2', text)
        text = re.sub(r'(\])([A-Za-z0-9])', r'\1 \2', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

if __name__ == "__main__":
    # Test
    redactor = AirlinePIIRedactor()
    test_texts = [
        "Passenger John Smith contact +1-555-555-5555",
        "Customer 李明 booked flight MU567",
        "PNR is X9Y8Z7.",
        "My ticket number is 176-1234567890.",
        "Frequent flyer AA12345678 has 5000 miles.",
        "I was born on 1990-05-20 and want to fly tomorrow."
    ]
    for t in test_texts:
        print(f"Original: {t}")
        print(f"Redacted: {redactor.redact(t)}")
        print("-" * 20)
