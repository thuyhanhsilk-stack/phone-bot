import logging
import os
import sys
import json
import io
from datetime import datetime
from PIL import Image
import re

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

try:
    import pytesseract
except ImportError:
    print("Chưa cài pytesseract. Vui lòng chạy: pip install pytesseract")
    sys.exit(1)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")

if not TELEGRAM_TOKEN or not GOOGLE_SHEETS_ID or not SERVICE_ACCOUNT_JSON:
    logger.error("❌ Lỗi: Thiếu biến trong file .env")
    sys.exit(1)


class PhoneExtractor:
    """Lớp để trích xuất số điện thoại từ ảnh"""
    
    @staticmethod
    def extract_phones(image_bytes):
        """Đọc ảnh và trích xuất số điện thoại"""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img, lang='vie')
            logger.info(f"📄 OCR text: {text[:100]}...")
            
            patterns = [
                r'0\d{9}',
                r'0\d{3}-\d{3}-\d{4}',
                r'0\d{3}\s\d{3}\s\d{4}',
                r'\+84\d{9,10}',
            ]
            
            phones = []
            for pattern in patterns:
                matches = re.findall(pattern, text)
                phones.extend(matches)
            
            phones = list(set(phones))
            return phones, text
        
        except Exception as e:
            logger.error(f"❌ Lỗi OCR: {e}")
            return [], ""


class SheetManager:
    """Lớp quản lý Google Sheets"""
    
    def __init__(self):
        self.client = None
        self.worksheet = None
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
            
            logger.info("✅ Kết nối Google Sheets thành công")
        
        except Exception as e:
            logger.error(f"❌ Lỗi kết nối Google Sheets: {e}")
            self.worksheet = None
    
    def add_phones(self, phones, user_id, username):
        """Thêm số điện thoại vào Google Sheet"""
        try:
            if not self.worksheet:
                logger.error("❌ Không có kết nối Google Sheets")
                return False
            
            try:
                first_row = self.worksheet.row_values(1)
                if not first_row or first_row[0] == "":
                    self.worksheet.insert_row([
                        "Thời gian",
                        "Số điện thoại",
                        "User ID",
                        "Tên người dùng",
                        "Trạng thái",
                        "Thời gian gửi",
                        "Kịch bản"
                    ], index=1)
                    logger.info("✅ Tạo header Google Sheet")
            except:
                pass
            
            for phone in phones:
                row = [
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    phone,
                    str(user_id),
                    username or "Unknown",
                    "⏳ Chờ",
                    "-",
                    "2"
                ]
                self.worksheet.append_row(row)
                logger.info(f"✅ Thêm {phone}")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Lỗi thêm dữ liệu: {e}")
            return False


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi nhận ảnh"""
    try:
        status_msg = await update.message.reply_text("⏳ Đang xử lý ảnh...")
        
        logger.info(f"📸 Nhận ảnh từ @{update.message.from_user.username}")
        
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        extractor = PhoneExtractor()
        phones, ocr_text = extractor.extract_phones(bytes(image_bytes))
        
        if not phones:
            await status_msg.edit_text(
                "❌ Không tìm thấy số điện thoại trong ảnh\n\n"
                "Vui lòng kiểm tra:\n"
                "- Ảnh phải rõ ràng\n"
                "- Chữ phải dễ đọc\n"
                "- Số phải là số điện thoại Việt Nam (0xxx...)"
            )
            logger.warning(f"OCR text: {ocr_text[:100]}")
            return
        
        manager = SheetManager()
        success = manager.add_phones(
            phones,
            update.message.from_user.id,
            update.message.from_user.username or update.message.from_user.first_name
        )
        
        if success:
            phone_list = "\n".join([f"  ✓ {p}" for p in phones])
            result = f"✅ Thêm thành công!\n\nSố điện thoại:\n{phone_list}\n\n⏱️ Sau 30 phút sẽ tự động gửi tin Zalo"
            await status_msg.edit_text(result)
        else:
            await status_msg.edit_text("❌ Lỗi lưu vào Google Sheets")
    
    except Exception as e:
        logger.error(f"❌ Lỗi: {e}")
        try:
            await update.message.reply_text(f"❌ Lỗi: {str(e)}")
        except:
            pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /start"""
    await update.message.reply_text(
        "👋 Xin chào! Tôi là bot tự động đọc số điện thoại.\n\n"
        "📱 Cách sử dụng:\n"
        "1. Gửi ảnh chụp màn hình chứa số điện thoại\n"
        "2. Bot sẽ tự động đọc số điện thoại\n"
        "3. Lưu vào Google Sheets\n"
        "4. Sau 30 phút sẽ tự động gửi tin Zalo\n\n"
        "⚠️ Lưu ý: Ảnh phải rõ ràng, chữ dễ đọc"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /help"""
    await update.message.reply_text(
        "📖 Trợ giúp:\n\n"
        "/start - Bắt đầu\n"
        "/help - Hiển thị trợ giúp\n"
        "/status - Kiểm tra trạng thái bot\n\n"
        "Gửi ảnh bất kỳ lúc nào để trích xuất số điện thoại"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /status"""
    try:
        manager = SheetManager()
        if manager.worksheet:
            await update.message.reply_text("✅ Bot Telegram đang hoạt động bình thường")
        else:
            await update.message.reply_text("⚠️ Không thể kết nối Google Sheets")
    except:
        await update.message.reply_text("❌ Lỗi kết nối")


def main():
    """Hàm chính"""
    logger.info("🚀 Bot Telegram đang khởi động...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Command(), start))
    
    logger.info("✅ Bot Telegram đã khởi động thành công!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()