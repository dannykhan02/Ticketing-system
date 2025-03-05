import re
import phonenumbers as pn

# Safaricom valid prefixes
SAFARICOM_PREFIXES = {
    "0701", "0702", "0703", "0704", "0705", "0706", "0707", "0708", "0709",
    "0710", "0711", "0712", "0713", "0714", "0715", "0716", "0717", "0718", "0719",
    "0720", "0721", "0722", "0723", "0724", "0725", "0726", "0727", "0728", "0729",
    "0740", "0741", "0742", "0743", "0744", "0745", "0746", "0747", "0748", "0749",
    "0757", "0758",
    "0768", "0769",
    "0790", "0791", "0792", "0793", "0794", "0795", "0796", "0797", "0798", "0799",
    "0110", "0111", "0112", "0113", "0114", "0115"
}

def normalize_phone(phone: str) -> str:
    """ Converts phone numbers to a standard format: 07xxxxxxxx """
    phone = phone.replace(" ", "").replace("-", "")  # Remove spaces & dashes
    phone = re.sub(r"\D", "", phone)  # Remove non-numeric characters

    print(f"Step 1: Raw Input Phone: {phone}")  # Debugging Output

    if phone.startswith("+254"):
        phone = "0" + phone[4:]
    elif phone.startswith("254") and len(phone) == 12:
        phone = "0" + phone[3:]

    print(f"Step 2: Normalized Phone: {phone}")  # Debugging Output
    return phone

def is_valid_safaricom_phone(phone: str, region="KE") -> bool:
    """ Validates if the phone number is a valid Safaricom number. """
    phone = normalize_phone(phone)  # Normalize first

    # Validate using phonenumbers library
    try:
        parsed_number = pn.parse(phone, region)
        if not pn.is_valid_number(parsed_number):
            print("Step 3: Invalid number according to phonenumbers library")
            return False
    except pn.phonenumberutil.NumberParseException:
        print("Step 3: Error parsing phone number")
        return False

    # Extract correct prefix from normalized phone number
    if len(phone) >= 10:
        prefix = phone[:4]  # Extract first 4 digits
    else:
        print(f"Step 4: Unexpected number format: {phone}")
        return False

    print(f"Step 4: Extracted Prefix: {prefix}")  # Debugging Output

    if prefix in SAFARICOM_PREFIXES:
        print("Step 5: Valid Safaricom Number ✅")
        return True
    else:
        print("Step 5: Invalid Prefix ❌")
        return False

# **Testing Your Number**
test_number = "0746604602"
print(f"Testing {test_number}: {is_valid_safaricom_phone(test_number)}")
