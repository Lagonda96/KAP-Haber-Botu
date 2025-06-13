# --- 1. GEREKLİ KÜTÜPHANELER ---
import requests
import time
import os
import fitz
import google.generativeai as genai
import pandas as pd
import json
from flask import Flask
from threading import Thread

# --- 2. AYARLAR ve GÜVENLİ Secrets OKUMA ---
# Bu kod, çalışacağı sunucunun (Render/Replit) "Environment Variables" veya "Secrets"
# bölümünden anahtarları güvenli bir şekilde okumak için tasarlanmıştır.
# Kodun içinde asla doğrudan anahtar yazılmaz.
try:
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
except Exception as e:
    print(f"HATA: Ortam değişkenleri (API Anahtarları) okunurken bir sorun oluştu: {e}")
    # Eğer anahtarlar okunamıyorsa, programın devam etmesinin bir anlamı yok.
    exit()

# Diğer ayarlar
HAFIZA_DOSYASI = "son_id.txt"
BEKLEME_SURESI = 600 # 10 dakika
ARSIV_KLASORU = "KAP_Arsiv"
API_BEKLEME = 5
ONEMLI_KATEGORILER = ["pay geri alım", "yeni iş ilişkisi", "sözleşme", "yatırım teşvik", "bedelsiz", "bedelli", "temettü", "transfer", "birleşme", "devralma", "satın alma", "önemli yatırım"]
GEREKSIZ_KATEGORILER = ["repo", "ters repo", "genel kurul", "sorumluluk beyanı", "denetim firması", "finansal rapor"]


# --- 3. YAPI ZEKÂ MODELİNİ YAPILANDIR ---
model = None
# Anahtarların hepsinin var olup olmadığını kontrol et
if all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GOOGLE_API_KEY]):
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Google Gemini modeli başarıyla yapılandırıldı.")
    except Exception as e:
        print(f"HATA: Google Gemini modeli yapılandırılamadı: {e}")
else:
    print("HATA: Lütfen sunucunun 'Environment Variables' (Ortam Değişkenleri) bölümündeki tüm anahtarları kontrol edin.")


# --- 4. WEB SUNUCUSU (BOTU UYANIK TUTMAK İÇİN) ---
app = Flask(__name__)
@app.route('/')
def home():
    # Bu sayfa, UptimeRobot'un botu "dürtmesi" için var.
    return "KAP Haber Botu Aktif ve Çalışıyor."
def run_web_server():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))


# --- 5. YARDIMCI FONKSİYONLAR ---
def son_id_oku():
    baslangic_id_manuel = 1448375 # Güncel bir ID
    if not os.path.exists(HAFIZA_DOSYASI):
        with open(HAFIZA_DOSYASI, "w") as f: f.write(str(baslangic_id_manuel))
        return baslangic_id_manuel
    with open(HAFIZA_DOSYASI, "r") as f:
        try: return int(f.read().strip())
        except: return baslangic_id_manuel

def son_id_yaz(yeni_id):
    with open(HAFIZA_DOSYASI, "w") as f: f.write(str(yeni_id))

def pdf_dosyasindan_metin_cek(dosya_yolu):
    tam_metin = ""
    try:
        with fitz.open(dosya_yolu) as doc:
            for page in doc:
                tam_metin += page.get_text()
    except Exception as e:
        print(f" -> PDF okuma hatası: {e}")
        return ""
    return tam_metin

def yapay_zekadan_analiz_iste(bildirim_metni):
    if not model: return None
    print("   -> Ham metin Usta Analist modunda Yapay Zeka'ya gönderiliyor...")
    try:
        time.sleep(API_BEKLEME)
        prompt = f'Bir yatırım bankasının kıdemli analisti gibi davran. Aşağıdaki KAP bildirimini analiz et ve Borsa İstanbul yatırımcıları için "aksiyon alınabilir" ve "net" bir çıktı oluştur. Cevabın MUTLAKA JSON formatında olsun. 1. "sirket_adi" 2. "hisse_kodu" (Bulamazsan "YOK" yaz) 3. "kategori" (Asla "Özel Durum Açıklaması (Genel)" kullanma) 4. "onem_derecesi" (1-10) 5. "ozet" (2 cümle) 6. "yatirimci_yorumu". --- BİLDİRİM METNİ: {bildirim_metni}'
        response = model.generate_content(prompt, request_options={'timeout': 100})
        temiz_cevap = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(temiz_cevap)
    except Exception as e:
        print(f"   -> HATA: AI analizi sırasında: {e}")
        return None

def arsive_kaydet(analiz_sonucu, bildirim_id):
    try:
        hisse_kodu = analiz_sonucu.get("hisse_kodu", "YOK")
        if not hisse_kodu or hisse_kodu == "YOK":
            sirket_adi = analiz_sonucu.get("sirket_adi", "BILINMEYEN_SIRKET")
            hisse_kodu = sirket_adi.split()[0].upper()
        hisse_kodu = hisse_kodu.upper()
        
        if not os.path.exists(ARSIV_KLASORU): os.makedirs(ARSIV_KLASORU)
        dosya_yolu = os.path.join(ARSIV_KLASORU, f"{hisse_kodu}.xlsx")
        
        yeni_veri = {'Tarih': [time.strftime('%Y-%m-%d %H:%M:%S')],'Bildirim_ID': [bildirim_id],'Kategori': [analiz_sonucu.get("kategori")],'Önem': [analiz_sonucu.get("onem_derecesi")],'Özet': [analiz_sonucu.get("ozet")],'Yorum': [analiz_sonucu.get("yatirimci_yorumu")],'Link': [f"https://www.kap.org.tr/tr/Bildirim/{bildirim_id}"]}
        yeni_df = pd.DataFrame(yeni_veri)

        if os.path.exists(dosya_yolu):
            eski_df = pd.read_excel(dosya_yolu)
            birlesik_df = pd.concat([eski_df, yeni_df], ignore_index=True)
        else:
            birlesik_df = yeni_df
            
        birlesik_df.to_excel(dosya_yolu, index=False)
        print(f"   -> Bildirim {dosya_yolu} dosyasına başarıyla arşivlendi.")
    except Exception as e:
        print(f"   -> HATA: Arşivleme sırasında: {e}")

def telegrama_gonder(analiz_sonucu, bildirim_linki):
    try:
        hisse_kodu = analiz_sonucu.get("hisse_kodu", "YOK")
        kategori = analiz_sonucu.get("kategori", "Önemli Gelişme")
        ozet = analiz_sonucu.get("ozet", "Detaylar için linke tıklayın.")
        yorum = analiz_sonucu.get("yatirimci_yorumu", "")
        baslik_str = f"<b>🔔 {kategori.upper()}</b>"
        if hisse_kodu != "YOK":
            baslik_str += f" | ${hisse_kodu.upper()}"
        mesaj = (f"{baslik_str}\n\n"
                 f"<b>Özet:</b> {ozet}\n\n"
                 f"<b>Analist Yorumu:</b> {yorum}\n\n"
                 f"<b>Kaynak:</b> <a href='{bildirim_linki}'>Bildirimi Görüntüle</a>")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': mesaj, 'parse_mode': 'HTML'}
        requests.post(url, json=payload, timeout=10)
        print("   -> TELEGRAM BİLDİRİMİ GÖNDERİLDİ!")
    except Exception as e:
        print(f"   -> HATA: Telegram mesajı oluşturulurken: {e}")

# --- 6. ANA PROGRAM DÖNGÜSÜ ---
if model:
    # Önce web sunucusunu arka planda çalıştır.
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()
    
    print("\nKAP Usta Analist & Telegram Botu (Render v1.0) Başlatıldı...")
    print("="*60)
    
    while True:
        try:
            en_son_bilinen_id = son_id_oku()
            siradaki_id = en_son_bilinen_id + 1
            print(f"[{time.strftime('%H:%M:%S')}] Kontrol: {siradaki_id}...")
            
            pdf_url = f"https://www.kap.org.tr/tr/api/BildirimPdf/{siradaki_id}"
            head_response = requests.head(pdf_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)

            if head_response.status_code == 200:
                print(f"✅ YENİ BİLDİRİM: {siradaki_id}")
                
                response = requests.get(pdf_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
                gecici_dosya_yolu = "gecici_bildirim.pdf"
                with open(gecici_dosya_yolu, 'wb') as f: f.write(response.content)
                ham_metin = pdf_dosyasindan_metin_cek(gecici_dosya_yolu)
                os.remove(gecici_dosya_yolu)
                
                if ham_metin.strip():
                    analiz_sonucu = yapay_zekadan_analiz_iste(ham_metin)
                    if analiz_sonucu:
                        arsive_kaydet(analiz_sonucu, siradaki_id)
                        kategori = analiz_sonucu.get("kategori", "").lower()
                        onem = analiz_sonucu.get("onem_derecesi", 0)
                        
                        is_unimportant = any(kelime in kategori for kelime in GEREKSIZ_KATEGORILER)
                        is_important = any(kelime in kategori for kelime in ONEMLI_KATEGORILER) or onem >= 7
                        
                        if is_important and not is_unimportant:
                            print("\n" + "⚠️ ÖNEMLİ HABER! Telegram'a gönderiliyor... " + "⚠️")
                            telegrama_gonder(analiz_sonucu, f"https://www.kap.org.tr/tr/Bildirim/{siradaki_id}")
                            print("-" * 35 + "\n")
                        else:
                            print(f"   -> '{kategori}' kategorisi rutin, gönderilmeyecek.")
                
                son_id_yaz(siradaki_id)
                continue
            
            print(f"   -> Yeni bildirim yok. {int(BEKLEME_SURESI / 60)} dk sonra tekrar denenecek.")
            time.sleep(BEKLEME_SURESI)

        except KeyboardInterrupt:
            print("\nProgram kullanıcı tarafından durduruldu.")
            break 
        except Exception as e:
            print(f"HATA: {e}. 60 saniye sonra devam edilecek.")
            time.sleep(60)
else:
    print("\nProgram başlatılamadı. Lütfen sunucudaki Ortam Değişkenlerini (Environment Variables) kontrol edin.")