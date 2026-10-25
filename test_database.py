from database import initialize_database, authenticate_user


initialize_database()


print("\nTesting Management Login...")

management = authenticate_user(
    "admin",
    "admin123",
    "management"
)

if management:
    print("Management login: SUCCESS")
    print("Name:", management["name"])
    print("Role:", management["role"])
else:
    print("Management login: FAILED")


print("\nTesting Retailer Login...")

retailer = authenticate_user(
    "retailer1",
    "retail123",
    "retailer"
)

if retailer:
    print("Retailer login: SUCCESS")
    print("Name:", retailer["name"])
    print("Role:", retailer["role"])
else:
    print("Retailer login: FAILED")