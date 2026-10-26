from flask import Flask,jsonify,render_template,request
import checker
import database
import scraper

app=Flask(__name__)
database.create_tables()

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/check", methods=["POST"])
def api_check():
    data = request.get_json(silent=True) or {}
    result = checker.run_check(
        data.get("domain", ""),
        data.get("slack_webhook", "").strip(),
        data.get("email_to", "").strip(),
        data.get("send_alert", True),
    )
    return jsonify(result)


@app.route("/api/sites")
def api_sites():
    return jsonify(database.list_sites())


@app.route("/api/reset", methods=["POST"])
def api_reset():
    data = request.get_json(silent=True) or {}
    try:
        domain = scraper.clean_domain(data.get("domain", ""))
    except scraper.ScrapeError as error:
        return jsonify({"status": error.code, "message": error.message}), 400
    database.reset_site(domain)
    return jsonify({"status": "ok"})


@app.route("/api/forget-latest", methods=["POST"])
def api_forget_latest():
    data = request.get_json(silent=True) or {}
    try:
        domain = scraper.clean_domain(data.get("domain", ""))
    except scraper.ScrapeError as error:
        return jsonify({"status": error.code, "message": error.message}), 400
    if database.forget_latest_post(domain):
        return jsonify({"status": "ok"})
    return jsonify({"status": "nothing_to_forget"})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)