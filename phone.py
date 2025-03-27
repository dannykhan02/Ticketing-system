import re

# Safaricom valid prefixes
SAFARICOM_PREFIXES = {
    "0701", "0702", "0703", "0704", "0705", "0706", "0707", "0708", "0709",
    "0710", "0711", "0712", "0713", "0714", "0715", "0716", "0717", "0718", "0719",
    "0720", "0721", "0722", "0723", "0724", "0725", "0726", "0727", "0728", "0729",
    "0740", "0741", "0742", "0743", "0744", "0745", "0746", "0747", "0748", "0749",
    "0757", "0758", "0768", "0769",
    "0790", "0791", "0792", "0793", "0794", "0795", "0796", "0797", "0798", "0799",
    "0110", "0111", "0112", "0113", "0114", "0115"
}

def normalize_phone(phone: str) -> str:
    """ Converts phone numbers to a standard Safaricom format (07xxxxxxxx) """
    if not isinstance(phone, str):  # Ensure input is a string
        return ""

    phone = re.sub(r"\D", "", phone)  # Remove all non-numeric characters

    if phone.startswith("+254"):
        phone = "0" + phone[4:]
    elif phone.startswith("254") and len(phone) == 12:
        phone = "0" + phone[3:]

    return phone

def is_valid_safaricom_phone(phone: str) -> bool:
    """ Checks if the phone number is a valid Safaricom number """
    phone = normalize_phone(phone)
    
    if len(phone) != 10 or not phone.startswith("07") and not phone.startswith("01"):
        return False  # Kenyan phone numbers should be 10 digits, starting with 07 or 01

    prefix = phone[:4]
    return prefix in SAFARICOM_PREFIXES

def validate_password(password: str) -> bool:
    """ Password must be at least 8 characters long, containing letters and numbers """
    return bool(re.match(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$', password))

# Test Cases
user_data = {
    "email": "danielkemboi462@gmail.com",
    "phone_number": "0746604602",
    "password": "password123"
}

phone_valid = is_valid_safaricom_phone(user_data["phone_number"])
password_valid = validate_password(user_data["password"])

if not phone_valid:
    print({"msg": "Invalid phone number. Must be a valid Safaricom number."})
elif not password_valid:
    print({"msg": "Invalid password. Must be at least 8 characters with letters and numbers."})
else:
    print({"msg": "Valid credentials."})
