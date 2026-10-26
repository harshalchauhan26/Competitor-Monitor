import checker
import database

database.create_tables()
for site in database.list_sites():
    result = checker.run_check(site["domain"])
    print(site["domain"], "->", result["status"], "-", result.get("message", ""))