# Словник довжин IBAN для основних країн (розширюється за потреби)
COUNTRY_LENGTHS = {
    "UA": 29, "DE": 22, "GB": 22, "FR": 27, "IT": 27, "ES": 24, "PL": 28,
    "NL": 18, "BE": 16, "AT": 20, "CH": 21, "PT": 25, "SE": 24, "NO": 15,
    "DK": 18, "FI": 18, "IE": 22, "CZ": 24, "HU": 28, "RO": 24, "BG": 22,
    "HR": 21, "LT": 20, "LV": 21, "EE": 20, "SK": 24, "SI": 19, "GR": 27,
    "CY": 28, "MT": 31, "LU": 20, "IS": 26, "TR": 26, "IL": 23, "GE": 22
}

def validate_iban(iban: str) -> dict:
    """
    Валідація IBAN за стандартом ISO 13616.
    """
    errors = []
    # 1. Нормалізація
    clean_iban = iban.replace(" ", "").replace("-", "").upper()
    
    if len(clean_iban) < 2:
        return {"valid": False, "iban": clean_iban, "errors": ["IBAN is too short"]}

    country_code = clean_iban[:2]
    
    # 2. Перевірка країни та довжини
    if country_code not in COUNTRY_LENGTHS:
        errors.append(f"Unknown country code: {country_code}")
    elif len(clean_iban) != COUNTRY_LENGTHS[country_code]:
        errors.append(f"Invalid length for {country_code}. Expected {COUNTRY_LENGTHS[country_code]}, got {len(clean_iban)}")

    # 3. Перевірка символів (тільки букви та цифри)
    if not clean_iban.isalnum():
        errors.append("IBAN contains invalid characters")

    # 4. Математична валідація MOD97-10 (якщо попередні кроки пройдені)
    if not errors:
        # Переміщуємо перші 4 символи в кінець
        rearranged = clean_iban[4:] + clean_iban[:4]
        # Конвертуємо букви в цифри (A=10, B=11 ... Z=35)
        numeric_string = ""
        for char in rearranged:
            if char.isdigit():
                numeric_string += char
            else:
                numeric_string += str(ord(char) - 55)
        
        if int(numeric_string) % 97 != 1:
            errors.append("Failed MOD97-10 checksum")

    return {
        "valid": len(errors) == 0,
        "iban": clean_iban,
        "country_code": country_code if country_code in COUNTRY_LENGTHS else None,
        "length": len(clean_iban),
        "errors": errors
    }
