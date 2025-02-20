import jwt

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJmcmVzaCI6ZmFsc2UsImlhdCI6MTczOTk4NTc1OCwianRpIjoiZDg0MDMzN2MtMjI3Mi00M2E5LTkxYTgtOTRiZWFjZTNhZTk1IiwidHlwZSI6ImFjY2VzcyIsInN1YiI6IjUiLCJuYmYiOjE3Mzk5ODU3NTgsImNzcmYiOiI0NjIwODYxMS1mMmNiLTQxZDQtOTA3NS0wNDk1NDM3YTA2MjQiLCJleHAiOjE3NDI1Nzc3NTgsImVtYWlsIjoib3JnYW5pemVyMTIzQGdtYWlsLmNvbSIsInJvbGUiOiJPUkdBTklaRVIifQ.YP2ZWAzjjSxp5l6VlmXkLye-iZL8BMnX78_EsTAm5hs"  # Replace with an actual token
try:
    decoded = jwt.decode(token, options={"verify_signature": False})  # No verification for debugging
    print(decoded)
except jwt.exceptions.InvalidTokenError as e:
    print("Invalid JWT:", e)
