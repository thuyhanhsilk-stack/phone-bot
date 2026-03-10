import logging
import os
import json
import time
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
ZALO_PHONE = os.getenv("ZALO_PHONE")
ZALO_PASSWORD = os.getenv("ZALO_PASSWORD")
SHOP_NAME = os.getenv("SHOP_NAME", "Shop Đồ Chơi Mình")

DELAY_MINUTES = 30
DELAY_SECONDS = DELAY_MINUTES * 60

if not all([GOOGLE_SHEETS_ID, SERVICE_ACCOUNT_JSON, ZALO_PHONE, ZALO_PASSWORD]):
    logger.error("❌ Lỗi: Thiếu biến trong file .env")
    exit(1)


class ZaloSender:
    """Lớp để gửi tin nhắn Zalo"""
    
    def __init__(self):
        self.driver = None
        self.sheet_manager = SheetManager()
        self.is_logged_in = False
    
    def init_driver(self):
        """Khởi tạo Chrome driver"""
        try:
            options = Options()
            options.add_argument("--start-maximized")
            options.add_argument("--disable-notifications")
            options.add_argument("--disable-popup-blocking")
            
            self.driver = webdriver.Chrome(options=options)
            logger.info("✅ Chrome driver khởi tạo thành công")
            return True
        except Exception as e:
            logger.error(f"❌ Lỗi khởi tạo Chrome: {e}")
            return False
    
    def login_zalo(self):
        """Đăng nhập Zalo"""
        try:
            logger.info("🔐 Đang đăng nhập Zalo...")
            
            self.driver.get("https://chat.zalo.me")
            time.sleep(5)
            
            try:
                phone_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Số điện thoại']"))
                )
                phone_input.send_keys(ZALO_PHONE)
                time.sleep(1)
                
                password_input = self.driver.find_element(By.XPATH, "//input[@placeholder='Mật khẩu']")
                password_input.send_keys(ZALO_PASSWORD)
                time.sleep(1)
                
                login_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Đăng nhập')]")
                login_button.click()
                
                time.sleep(5)
                
                logger.info("✅ Đăng nhập Zalo thành công")
                self.is_logged_in = True
                return True
            
            except Exception as e:
                logger.error(f"❌ Lỗi đăng nhập: {e}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Lỗi: {e}")
            return False
    
    def send_friend_request(self, phone_number, message, name):
        """Gửi lời mời kết bạn + tin nhắn"""
        try:
            logger.info(f"📤 Đang gửi tin tới {phone_number}...")
            
            search_box = self.driver.find_element(By.XPATH, "//input[@placeholder='Tìm kiếm']")
            search_box.clear()
            search_box.send_keys(phone_number)
            time.sleep(3)
            
            try:
                contact = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'contact-item')]"))
                )
                contact.click()
                time.sleep(2)
            except:
                logger.warning(f"⚠️ Không tìm thấy {phone_number} trên Zalo")
                return False, "Không tìm thấy số"
            
            try:
                add_friend_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Thêm bạn')]")
                add_friend_button.click()
                time.sleep(2)
                logger.info(f"✅ Gửi lời mời kết bạn {phone_number}")
            except:
                pass
            
            try:
                message_box = self.driver.find_element(By.XPATH, "//textarea[@placeholder='Nhập tin nhắn...']")
                message_box.clear()
                message_box.send_keys(message)
                time.sleep(1)
                
                send_button = self.driver.find_element(By.XPATH, "//button[@class='send-button']")
                send_button.click()
                time.sleep(2)
                
                logger.info(f"✅ Gửi tin nhắn tới {phone_number} thành công")
                return True, "Thành công"
            
            except Exception as e:
                logger.error(f"❌ Lỗi gửi tin nhắn: {e}")
                return False, str(e)
        
        except Exception as e:
            logger.error(f"❌ Lỗi: {e}")
            return False, str(e)
    
    def close_driver(self):
        """Đóng Chrome driver"""
        try:
            if self.driver:
                self.driver.quit()
                logger.info("✅ Chrome driver đã đóng")
        except Exception as e:
            logger.error(f"❌ Lỗi đóng driver: {e}")


class SheetManager:
    """Lớp quản lý Google Sheets"""
    
    def __init__(self):
        self.client = None
        self.worksheet = None
        self.script_sheet = None
        self.authenticate()
    
    def authenticate(self):
        """Xác thực với Google Sheets API"""
        try:
            service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
            creds = Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            
            self.client = gspread.authorize(creds)
            spreadsheet = self.client.open_by_key(GOOGLE_SHEETS_ID)
            self.worksheet = spreadsheet.sheet1
            
            try:
                self.script_sheet = spreadsheet.get_worksheet(1)
            except:
                logger.warning("⚠️ Không tìm thấy sheet 'Kịch bản'")
            
            logger.info("✅ Kết nối Google Sheets thành công")
        
        except Exception as e:
            logger.error(f"❌ Lỗi kết nối Google Sheets: {e}")
    
    def get_pending_phones(self):
        """Lấy danh sách số chưa gửi"""
        try:
            if not self.worksheet:
                return []
            
            all_rows = self.worksheet.get_all_records()
            
            pending = []
            for idx, row in enumerate(all_rows, start=2):
                if row.get("Trạng thái", "") == "⏳ Chờ":
                    time_str = row.get("Thời gian", "")
                    if time_str:
                        try:
                            time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                            if datetime.now() >= time_obj + timedelta(seconds=DELAY_SECONDS):
                                pending.append({
                                    "row": idx,
                                    "phone": row.get("Số điện thoại", ""),
                                    "name": row.get("Tên người dùng", "Unknown"),
                                    "script_id": row.get("Kịch bản", "2")
                                })
                        except:
                            pass
            
            return pending
        
        except Exception as e:
            logger.error(f"❌ Lỗi lấy danh sách: {e}")
            return []
    
    def get_script(self, script_id):
        """Lấy nội dung kịch bản"""
        try:
            if not self.script_sheet:
                return None
            
            all_rows = self.script_sheet.get_all_records()
            
            for row in all_rows:
                if str(row.get("ID", "")) == str(script_id):
                    return row.get("Nội dung tin nhắn", "")
            
            return None
        
        except Exception as e:
            logger.error(f"❌ Lỗi lấy kịch bản: {e}")
            return None
    
    def update_status(self, row_num, status, message=""):
        """Cập nhật trạng thái gửi"""
        try:
            if not self.worksheet:
                return False
            
            self.worksheet.update_cell(row_num, 5, status)
            self.worksheet.update_cell(row_num, 6, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            logger.info(f"✅ Cập nhật trạng thái dòng {row_num}: {status}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Lỗi cập nhật trạng thái: {e}")
            return False


def process_zalo_messages():
    """Hàm chính xử lý gửi tin Zalo"""
    logger.info("🔍 Kiểm tra danh sách chờ gửi...")
    
    sheet_manager = SheetManager()
    pending_list = sheet_manager.get_pending_phones()
    
    if not pending_list:
        logger.info("ℹ️ Không có số chờ gửi")
        return
    
    logger.info(f"📋 Tìm thấy {len(pending_list)} số chờ gửi")
    
    sender = ZaloSender()
    
    if not sender.init_driver():
        logger.error("❌ Không thể khởi tạo Chrome driver")
        return
    
    if not sender.login_zalo():
        logger.error("❌ Không thể đăng nhập Zalo")
        sender.close_driver()
        return
    
    for item in pending_list:
        try:
            phone = item["phone"]
            name = item["name"]
            script_id = item["script_id"]
            row_num = item["row"]
            
            script = sheet_manager.get_script(script_id)
            if not script:
                logger.warning(f"⚠️ Không tìm thấy kịch bản {script_id}")
                sheet_manager.update_status(row_num, "❌ Lỗi", "Không tìm thấy kịch bản")
                continue
            
            message = script.replace("[TÊN]", name)
            message = message.replace("[SỐ]", phone)
            message = message.replace("[NGÀY]", datetime.now().strftime("%d-%m-%Y"))
            message = message.replace("[THỜI_GIAN]", datetime.now().strftime("%H:%M"))
            
            success, error = sender.send_friend_request(phone, message, name)
            
            if success:
                sheet_manager.update_status(row_num, "✅ Đã gửi")
            else:
                sheet_manager.update_status(row_num, "❌ Lỗi", error)
            
            time.sleep(15)
        
        except Exception as e:
            logger.error(f"❌ Lỗi xử lý {phone}: {e}")
            sheet_manager.update_status(row_num, "❌ Lỗi", str(e))
    
    sender.close_driver()
    logger.info("✅ Xong quá trình gửi tin Zalo")


def start_scheduler():
    """Khởi động scheduler"""
    scheduler = BackgroundScheduler()
    
    scheduler.add_job(
        process_zalo_messages,
        'interval',
        minutes=5,
        id='zalo_sender_job'
    )
    
    scheduler.start()
    logger.info("✅ Scheduler khởi động thành công (kiểm tra mỗi 5 phút)")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("✅ Scheduler đã dừng")


if __name__ == "__main__":
    logger.info("🚀 Bot Zalo Sender đang khởi động...")
    start_scheduler()