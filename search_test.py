import requests
from bs4 import BeautifulSoup
import urllib.parse

def search_hall():
    query = "グランドダムズ県央"
    url = f"https://min-repo.com/?s={urllib.parse.quote(query)}"
    print(f"Searching on min-repo: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 検索結果から店舗へのタグリンクを探す
        # 通常、みんレポではタグページが店舗ごとのデータ一覧になっている可能性が高い
        # タグリンク例: https://min-repo.com/tag/グランドダムズ県央店/ や https://min-repo.com/tag/grand-damz県央/
        links = soup.find_all('a')
        
        found_links = []
        for link in links:
            href = link.get('href')
            text = link.get_text()
            if href and ("tag" in href or "category" in href or "min-repo.com" in href) and any(x in text for x in ["ダムズ", "DAMZ", "県央"]):
                found_links.append((text.strip(), href))
                
        # 重複を削除して出力
        unique_links = list(set(found_links))
        print(f"Found {len(unique_links)} related links:")
        for text, href in unique_links:
            print(f"Text: {text} | URL: {href}")
            
    except Exception as e:
        print(f"Error during search: {e}")

if __name__ == "__main__":
    search_hall()
