# 🏦 IBAN/BIC Validator API
Швидкий, безкоштовний (Zero-COGS) мікро-сервіс для валідації IBAN за стандартом ISO 13616 (MOD97-10).

## 🚀 Швидкий старт
API приймає `POST /v1/iban/validate` з JSON:
```json
{
  "iban": "UA21 3223 1300 0002 6007 2335 6600 1"
}
