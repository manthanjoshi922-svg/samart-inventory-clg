import mysql.connector
from getpass import getpass

password = getpass("Enter MySQL root password: ")

try:
    connection = mysql.connector.connect(
        host="localhost",
        port=3306,
        user="root",
        password=password,
        database="smart_inventory"
    )

    if connection.is_connected():
        print("MySQL connection successful!")
        print("Database: smart_inventory")

    connection.close()

except mysql.connector.Error as error:
    print("MySQL connection failed!")
    print(error)