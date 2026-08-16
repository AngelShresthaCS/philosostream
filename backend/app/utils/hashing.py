from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash(password: str):
    # Truncate to 72 bytes maximum to prevent bcrypt from choking
    encoded_password = password.encode('utf-8')
    if len(encoded_password) > 72:
        encoded_password = encoded_password[:72]
    return pwd_context.hash(encoded_password.decode('utf-8', errors='ignore'))
def verify(plain_password, hashedpassword):
    # Apply the exact same encoding/truncation logic used during creation
    encoded_password = plain_password.encode('utf-8')
    if len(encoded_password) > 72:
        encoded_password = encoded_password[:72]
    processed_password = encoded_password.decode('utf-8', errors='ignore')
    
    return pwd_context.verify(processed_password, hashedpassword)