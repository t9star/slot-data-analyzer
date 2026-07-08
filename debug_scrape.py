import requests

url = "https://min-repo.com/3213554/?kishu=all"
headers = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Response content length: {len(response.content)}")
    print("Snippet:")
    print(repr(response.text[:200]))
except Exception as e:
    print(f"Error: {e}")
