"""
Fast keyword-based category classifier — runs before AI to filter out irrelevant tenders.
"""


class CategoryClassifier:
    SOFTWARE_KEYWORDS = [
        "сайт", "веб", "web", "портал", "portal",
        "мобильн", "mobile", "приложени", "app",
        "программн", "software", "по ", " по,",
        "информационн", "систем", "system",
        "crm", "erp", "1с", "1c",
        "автоматизац", "automation",
        "платформ", "platform",
        "чат-бот", "chatbot", "чатбот",
        "искусственн", "artificial intelligence", " ai ",
        "цифров", "digital",
        "интеграц", "integration",
        "разработк", "development",
        "api", "микросервис", "microservice",
    ]

    # Services that should be excluded (NOT software)
    EXCLUDE_KEYWORDS = [
        "клинин", "уборк", "охран", "питани", "кейтер",
        "транспорт", "такси", "перевоз",
        "строительств", "ремонт", "монтаж",
        "медицинск", "лечени", "хирург",
        "юридическ", "legal", "адвокат",
        "бухгалтер", "аудит",
        "страховани", "insurance",
        "аренд", "лизинг",
    ]

    PRODUCT_INDICATORS = [
        "поставк", "supply", "товар", "goods",
        "оборудовани", "equipment",
        "материал", "material",
        "запасн", "spare part",
        "мебель", "furniture",
        "продукт", "product",
    ]

    def classify_quick(self, title: str, description: str = "") -> str:
        """
        Quick keyword-based classification.
        Returns: 'product' | 'software_service' | 'other' | 'uncertain'
        """
        text = (title + " " + (description or "")).lower()

        # Check exclusions first
        for kw in self.EXCLUDE_KEYWORDS:
            if kw in text:
                return "other"

        # Check software
        for kw in self.SOFTWARE_KEYWORDS:
            if kw in text:
                return "software_service"

        # Check product indicators
        for kw in self.PRODUCT_INDICATORS:
            if kw in text:
                return "product"

        # Uncertain — send to AI
        return "uncertain"
