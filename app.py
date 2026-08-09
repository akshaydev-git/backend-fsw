from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
from flask import Flask, request, send_file
from flask_cors import CORS
from bson import ObjectId
from openpyxl import Workbook
from functools import wraps
from io import BytesIO

import re
import random
import os
import jwt
import requests


# =========================================================
# APP SETUP
# =========================================================

app = Flask(__name__)
CORS(app)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()

mongo_uri = os.getenv("MONGO_URI")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
JWT_SECRET = os.getenv("JWT_SECRET")

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
BREVO_SENDER_NAME = os.getenv(
    "BREVO_SENDER_NAME",
    "FSW Recruitment"
)


# =========================================================
# MONGODB SETUP
# =========================================================

client = MongoClient(mongo_uri)

db = client["FSWRecruitment"]

applications_collection = db["applications"]

# One application per email
applications_collection.create_index(
    "email",
    unique=True
)


# =========================================================
# OTP / EMAIL VERIFICATION STORAGE
# =========================================================

otp_store = {}

# Email -> verification expiry time
verified_emails = {}


# =========================================================
# ADMIN AUTHENTICATION MIDDLEWARE
# =========================================================

def admin_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        auth_header = request.headers.get(
            "Authorization"
        )

        # Authorization header missing
        if not auth_header:
            return {
                "status": "error",
                "message": "Authorization token is required"
            }, 401

        # Check Bearer format
        if not auth_header.startswith("Bearer "):
            return {
                "status": "error",
                "message": "Invalid authorization format"
            }, 401

        token = auth_header.split(
            " ",
            1
        )[1]

        try:

            payload = jwt.decode(
                token,
                JWT_SECRET,
                algorithms=["HS256"]
            )

            # Check admin role
            if payload.get("role") != "admin":
                return {
                    "status": "error",
                    "message": "Admin access required"
                }, 403

            # Store admin information
            request.admin = payload

        except jwt.ExpiredSignatureError:

            return {
                "status": "error",
                "message": "Token has expired"
            }, 401

        except jwt.InvalidTokenError:

            return {
                "status": "error",
                "message": "Invalid token"
            }, 401

        return func(*args, **kwargs)

    return wrapper


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.post("/api/auth/admin/login")
def admin_login():

    data = request.get_json()

    if not data:
        return {
            "status": "error",
            "message": "Request body is required"
        }, 400

    username = data.get("username")
    password = data.get("password")

    # Username validation
    if not username:
        return {
            "status": "error",
            "message": "Username is required"
        }, 400

    # Password validation
    if not password:
        return {
            "status": "error",
            "message": "Password is required"
        }, 400

    # Check credentials
    if (
        username != ADMIN_USERNAME
        or password != ADMIN_PASSWORD
    ):
        return {
            "status": "error",
            "message": "Invalid username or password"
        }, 401

    # Create JWT
    token = jwt.encode(
        {
            "username": username,
            "role": "admin",
            "exp": (
                datetime.now(timezone.utc)
                + timedelta(hours=2)
            )
        },
        JWT_SECRET,
        algorithm="HS256"
    )

    return {
        "status": "success",
        "message": "Admin login successful",
        "token": token
    }, 200


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return {
        "status": "success",
        "message": "Welcome to FSW Recruitment API 🚀"
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
def health():

    try:

        client.admin.command("ping")

        return {
            "server": "running",
            "database": "connected"
        }, 200

    except Exception as e:

        return {
            "server": "running",
            "database": "disconnected",
            "error": str(e)
        }, 500


# =========================================================
# SEND EMAIL OTP
# =========================================================
import random
import smtplib
from email.message import EmailMessage
appkey=os.getenv("app_key")
def send_otp(receiver_email,otp):
            msg = EmailMessage()
            msg["Subject"] = "Email Verification OTP"
            msg["From"] = "akshayakash848@gmail.com"
            msg["To"] = receiver_email
            msg.set_content(
                f"Your verification OTP is: {otp}\n\n"
                "This OTP expires in 5 minutes."
            )
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(
                    "akshayakash848@gmail.com",
                    appkey
                )
                smtp.send_message(msg)
            

@app.post("/api/auth/email/send-otp")
def send_email_otp():

    data = request.get_json()

    if not data:
        return {
            "status": "error",
            "message": "Request body is required"
        }, 400

    email = data.get("email")

    # Email required
    if not email:
        return {
            "status": "error",
            "message": "Email is required"
        }, 400

    # Gmail validation
    email = email.strip().lower()

    email_pattern = r"^[A-Za-z0-9._%+-]+@grietcollege\.com$"
    
    if not re.fullmatch(
        email_pattern,
        email,
        re.IGNORECASE
    ):
        return {
            "status": "error",
            "message": "Please enter your valid GRIET college email address"
        }, 400

    # Generate 6-digit OTP
    otp = str(
        random.randint(
            100000,
            999999
        )
    )

    # Store OTP for 2 minutes
    otp_store[email] = {
        "otp": otp,
        "expires_at": (
            datetime.now()
            + timedelta(minutes=2)
        )
    }

    # =====================================================
    # SEND OTP THROUGH BREVO
    # =====================================================
    try:
        send_otp(email,otp)
        return {
        "status": "success",
        "message": "OTP sent successfully"
    }, 200
    
    except Exception as e:
        print(e)
        return {
                "status": "error",
                "message": (
                    "Unable to send verification email"
                )
            }, 502


   


# =========================================================
# VERIFY EMAIL OTP
# =========================================================

@app.post("/api/auth/email/verify-otp")
def verify_email_otp():

    data = request.get_json()

    if not data:
        return {
            "status": "error",
            "message": "Request body is required"
        }, 400

    email = data.get("email")
    otp = data.get("otp")

    # Email required
    if not email:
        return {
            "status": "error",
            "message": "Email is required"
        }, 400

    # OTP required
    if not otp:
        return {
            "status": "error",
            "message": "OTP is required"
        }, 400

    # Validate GRIET college email format
    email = email.strip().lower()
    
    email_pattern = (
        r"^[A-Za-z0-9._%+-]+@grietcollege\.com$"
    )
    
    if not re.fullmatch(
        email_pattern,
        email,
        re.IGNORECASE
    ):
        return {
            "status": "error",
            "message": (
                "Please enter your valid GRIET college email address"
            )
    }, 400

    # Find OTP
    otp_data = otp_store.get(email)

    if not otp_data:
        return {
            "status": "error",
            "message": "No OTP found for this email"
        }, 400

    # Check OTP expiry
    if datetime.now() > otp_data["expires_at"]:

        del otp_store[email]

        return {
            "status": "error",
            "message": "OTP has expired"
        }, 400

    # Check OTP
    if otp != otp_data["otp"]:

        return {
            "status": "error",
            "message": "Invalid OTP"
        }, 400

    # OTP is correct
    del otp_store[email]

    # Email verification remains valid for 10 minutes
    verified_emails[email] = (
        datetime.now()
        + timedelta(minutes=10)
    )

    return {
        "status": "success",
        "message": "Email verified successfully"
    }, 200


# =========================================================
# SEND APPLICATION CONFIRMATION EMAIL
# =========================================================

def send_application_confirmation_email(
    recipient_email,
    applicant_name,
    application_id
):
    """
    Send a confirmation email after an application
    has been successfully stored in MongoDB.
    """

    if (
        not BREVO_API_KEY
        or not BREVO_SENDER_EMAIL
    ):
        print(
            "Brevo is not configured. "
            "Confirmation email skipped."
        )

        return False

    email_payload = {

        "sender": {
            "name": BREVO_SENDER_NAME,
            "email": BREVO_SENDER_EMAIL
        },

        "to": [
            {
                "email": recipient_email,
                "name": applicant_name
            }
        ],

        "subject": (
            "FSW Recruitment 2026 - "
            "Application Received"
        ),

        "textContent": (
            f"Hi {applicant_name},\n\n"
            "Thank you for applying for "
            "Free Software Wing Recruitment 2026.\n\n"
            "We have successfully received "
            "your application.\n\n"
            f"Application ID: {application_id}\n\n"
            "Our recruitment team will review "
            "your application and contact you "
            "regarding the next steps.\n\n"
            "Please keep an eye on your email inbox.\n\n"
            "Best regards,\n"
            "Free Software Wing\n"
            "GRIET\n"
            "Recruitment Team"
        ),

        "htmlContent": f"""
        <!DOCTYPE html>
        <html>

        <head>
            <meta charset="UTF-8">
            <meta name="viewport"
                  content="width=device-width, initial-scale=1.0">

            <title>Application Received</title>
        </head>

        <body style="
            margin:0;
            padding:0;
            background:#050817;
            font-family:Arial,Helvetica,sans-serif;
        ">

            <div style="
                max-width:620px;
                margin:40px auto;
                padding:20px;
            ">

                <div style="
                    background:#091126;
                    border:1px solid #1c315b;
                    border-radius:20px;
                    padding:36px;
                    color:#f8faff;
                ">

                    <div style="
                        display:inline-block;
                        padding:7px 12px;
                        border-radius:999px;
                        background:#102957;
                        border:1px solid #244f9b;
                        color:#73aaff;
                        font-size:12px;
                        font-weight:700;
                        letter-spacing:0.5px;
                    ">
                        FSW RECRUITMENT 2026
                    </div>

                    <h1 style="
                        margin:24px 0 10px;
                        font-size:28px;
                        line-height:1.2;
                        color:#ffffff;
                    ">
                        Application received! 🚀
                    </h1>

                    <p style="
                        margin:0 0 20px;
                        color:#aab7ce;
                        font-size:15px;
                        line-height:1.7;
                    ">
                        Hi
                        <strong style="color:#ffffff;">
                            {applicant_name}
                        </strong>,
                    </p>

                    <p style="
                        color:#aab7ce;
                        font-size:15px;
                        line-height:1.7;
                    ">
                        Thank you for applying to
                        <strong style="color:#ffffff;">
                            Free Software Wing
                            Recruitment 2026
                        </strong>.
                        We've successfully received
                        your application.
                    </p>

                    <div style="
                        margin:28px 0;
                        padding:20px;
                        border-radius:14px;
                        background:#0d1933;
                        border:1px solid #1b3565;
                    ">

                        <div style="
                            color:#7283a0;
                            font-size:11px;
                            font-weight:700;
                            text-transform:uppercase;
                            letter-spacing:1px;
                            margin-bottom:8px;
                        ">
                            Application ID
                        </div>

                        <div style="
                            color:#73aaff;
                            font-size:16px;
                            font-weight:700;
                            word-break:break-all;
                        ">
                            {application_id}
                        </div>

                    </div>

                    <p style="
                        color:#aab7ce;
                        font-size:14px;
                        line-height:1.7;
                    ">
                        Our recruitment team will review
                        your application and contact you
                        regarding the next steps.
                        Please keep an eye on your inbox.
                    </p>

                    <div style="
                        height:1px;
                        background:#1b2b4d;
                        margin:28px 0;
                    "></div>

                    <p style="
                        margin:0;
                        color:#7d8da8;
                        font-size:12px;
                        line-height:1.6;
                    ">
                        This is an automated confirmation email.
                        Please do not reply to this message.
                    </p>

                    <p style="
                        margin:18px 0 0;
                        color:#dce6f7;
                        font-size:13px;
                        font-weight:700;
                    ">
                        — FSW Recruitment Team<br>
                        GRIET
                    </p>

                </div>

            </div>

        </body>
        </html>
        """
    }

    try:

        brevo_response = requests.post(
            "https://api.brevo.com/v3/smtp/email",

            headers={
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json"
            },

            json=email_payload,
            timeout=15
        )

        if not brevo_response.ok:

            print(
                "Brevo confirmation email error:",
                brevo_response.status_code,
                brevo_response.text
            )

            return False

        print(
            f"Confirmation email sent to "
            f"{recipient_email}"
        )

        return True

    except requests.RequestException as e:

        print(
            "Brevo confirmation email "
            "connection error:",
            str(e)
        )

        return False


# =========================================================
# SEND SELECTION EMAIL
# =========================================================

def send_selection_email(
    recipient_email,
    applicant_name
):
    """
    Send a selection email to an applicant who
    has cleared the application screening round.
    """

    if (
        not BREVO_API_KEY
        or not BREVO_SENDER_EMAIL
    ):
        print(
            "Brevo is not configured. "
            "Selection email skipped."
        )

        return False

    email_payload = {

        "sender": {
            "name": BREVO_SENDER_NAME,
            "email": BREVO_SENDER_EMAIL
        },

        "to": [
            {
                "email": recipient_email,
                "name": applicant_name
            }
        ],

        "subject": (
            "Congratulations! You Have Been Selected - "
            "FSW Recruitment 2026"
        ),

        "textContent": (
            f"Hi {applicant_name},\n\n"

            "Congratulations! 🎉\n\n"

            "We are pleased to inform you that you "
            "have been selected for the next round "
            "of the Free Software Wing Recruitment 2026.\n\n"

            "You have successfully cleared the "
            "application screening round.\n\n"

            "The next round will be conducted offline. "
            "Further details regarding the date, time, "
            "and venue will be communicated to you shortly.\n\n"

            "Please keep an eye on your email for "
            "further updates.\n\n"

            "Best regards,\n"
            "Free Software Wing\n"
            "GRIET\n"
            "Recruitment Team"
        ),

        "htmlContent": f"""
        <!DOCTYPE html>
        <html>

        <head>
            <meta charset="UTF-8">

            <meta name="viewport"
                  content="width=device-width, initial-scale=1.0">

            <title>
                You Have Been Selected
            </title>
        </head>

        <body style="
            margin:0;
            padding:0;
            background:#050817;
            font-family:Arial,Helvetica,sans-serif;
        ">

            <div style="
                max-width:620px;
                margin:40px auto;
                padding:20px;
            ">

                <div style="
                    background:#091126;
                    border:1px solid #1c315b;
                    border-radius:20px;
                    padding:36px;
                    color:#f8faff;
                ">

                    <div style="
                        display:inline-block;
                        padding:7px 12px;
                        border-radius:999px;
                        background:#102957;
                        border:1px solid #244f9b;
                        color:#73aaff;
                        font-size:12px;
                        font-weight:700;
                        letter-spacing:0.5px;
                    ">
                        FSW RECRUITMENT 2026
                    </div>

                    <h1 style="
                        margin:24px 0 10px;
                        font-size:30px;
                        line-height:1.2;
                        color:#ffffff;
                    ">
                        Congratulations! 🎉
                    </h1>

                    <p style="
                        margin:0 0 20px;
                        color:#aab7ce;
                        font-size:15px;
                        line-height:1.7;
                    ">
                        Hi
                        <strong style="color:#ffffff;">
                            {applicant_name}
                        </strong>,
                    </p>

                    <p style="
                        color:#aab7ce;
                        font-size:15px;
                        line-height:1.7;
                    ">
                        We are excited to inform you that
                        you have been
                        <strong style="color:#ffffff;">
                            selected for the next round
                        </strong>
                        of the
                        <strong style="color:#ffffff;">
                            Free Software Wing
                            Recruitment 2026
                        </strong>.
                    </p>

                    <div style="
                        margin:28px 0;
                        padding:22px;
                        border-radius:14px;
                        background:#0d1933;
                        border:1px solid #1b3565;
                    ">

                        <div style="
                            color:#7283a0;
                            font-size:11px;
                            font-weight:700;
                            text-transform:uppercase;
                            letter-spacing:1px;
                            margin-bottom:10px;
                        ">
                            Next Round
                        </div>

                        <div style="
                            color:#ffffff;
                            font-size:18px;
                            font-weight:700;
                            margin-bottom:8px;
                        ">
                            Offline Round
                        </div>

                        <div style="
                            color:#aab7ce;
                            font-size:14px;
                            line-height:1.6;
                        ">
                            Further details regarding the
                            date, time, and venue will be
                            communicated to you shortly.
                        </div>

                    </div>

                    <p style="
                        color:#aab7ce;
                        font-size:14px;
                        line-height:1.7;
                    ">
                        Please keep an eye on your email
                        inbox for further updates regarding
                        the recruitment process.
                    </p>

                    <div style="
                        height:1px;
                        background:#1b2b4d;
                        margin:28px 0;
                    "></div>

                    <p style="
                        margin:0;
                        color:#7d8da8;
                        font-size:12px;
                        line-height:1.6;
                    ">
                        This is an automated email from
                        the FSW Recruitment Team.
                    </p>

                    <p style="
                        margin:18px 0 0;
                        color:#dce6f7;
                        font-size:13px;
                        font-weight:700;
                    ">
                        — FSW Recruitment Team<br>
                        GRIET
                    </p>

                </div>

            </div>

        </body>
        </html>
        """
    }

    try:

        brevo_response = requests.post(
            "https://api.brevo.com/v3/smtp/email",

            headers={
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json"
            },

            json=email_payload,
            timeout=15
        )

        if not brevo_response.ok:

            print(
                "Brevo selection email error:",
                brevo_response.status_code,
                brevo_response.text
            )

            return False

        print(
            f"Selection email sent to "
            f"{recipient_email}"
        )

        return True

    except requests.RequestException as e:

        print(
            "Brevo selection email connection error:",
            str(e)
        )

        return False


# =========================================================
# CREATE APPLICATION
# =========================================================

@app.post("/api/applications")
def create_application():

    data = request.get_json()

    if not data:
        return {
            "status": "error",
            "message": "Request body is required"
        }, 400

    required_fields = [
        "fullName",
        "email",
        "phoneNumber",
        "gender",
        "department",
        "yearOfStudy",
        "rollNumber",
        "firstChoiceDomain",
        "whyFirstChoice",
        "secondChoiceDomain",
        "whySecondChoice",
        "whyJoinFSW",
        "skillsAndExperience",
        "academicBalance"
    ]

    # =====================================================
    # REQUIRED FIELD VALIDATION
    # =====================================================

    for field in required_fields:

        if (
            field not in data
            or data[field] in [None, ""]
        ):

            return {
                "status": "error",
                "message": f"{field} is required"
            }, 400

 
    # EMAIL VALIDATION
   
    
    data["email"] = data["email"].strip().lower()
    
    email_pattern = (
        r"^[A-Za-z0-9._%+-]+@grietcollege\.com$"
    )
    
    if not re.fullmatch(
        email_pattern,
        data["email"],
        re.IGNORECASE
    ):
    
        return {
            "status": "error",
            "message": (
                "Please enter your valid GRIET college email address"
            )
        }, 400

    # =====================================================
    # EMAIL VERIFICATION
    # =====================================================

    verification_expiry = verified_emails.get(
        data["email"]
    )

    if not verification_expiry:

        return {
            "status": "error",
            "message": "Email not verified"
        }, 400

    # Check verification expiry
    if datetime.now() > verification_expiry:

        del verified_emails[data["email"]]

        return {
            "status": "error",
            "message": (
                "Email verification expired. "
                "Please verify again."
            )
        }, 400

    # =====================================================
    # ALLOWED VALUES
    # =====================================================

    allowed_genders = [
        "Male",
        "Female"
    ]

    allowed_departments = [
        "CSE",
        "AIML",
        "CSBS",
        "CSDS",
        "ECE"
    ]

    allowed_years = [
        2,
        3
    ]

    allowed_domains = [
        "Public Relations",
        "Design & Social Media",
        "Technical",
        "Arts",
        "Event Management",
        "Logistics",
        "Publicity",
        "Documentation"
    ]

    # =====================================================
    # MOBILE VALIDATION
    # =====================================================

    if not re.fullmatch(
        r"[6-9]\d{9}",
        data["phoneNumber"]
    ):

        return {
            "status": "error",
            "message": (
                "Phone number must contain "
                "exactly 10 digits"
            )
        }, 400

    # =====================================================
    # GENDER VALIDATION
    # =====================================================

    if data["gender"] not in allowed_genders:

        return {
            "status": "error",
            "message": "Invalid gender"
        }, 400

    # =====================================================
    # DEPARTMENT VALIDATION
    # =====================================================

    if data["department"] not in allowed_departments:

        return {
            "status": "error",
            "message": "Invalid department"
        }, 400

    # =====================================================
    # YEAR VALIDATION
    # =====================================================

    if data["yearOfStudy"] not in allowed_years:

        return {
            "status": "error",
            "message": "Invalid year of study"
        }, 400

    # =====================================================
    # DOMAIN VALIDATION
    # =====================================================

    if (
        data["firstChoiceDomain"]
        not in allowed_domains
    ):

        return {
            "status": "error",
            "message": "Invalid first choice domain"
        }, 400

    if (
        data["secondChoiceDomain"]
        not in allowed_domains
    ):

        return {
            "status": "error",
            "message": "Invalid second choice domain"
        }, 400

    # =====================================================
    # FIRST AND SECOND CHOICE MUST BE DIFFERENT
    # =====================================================

    if (
        data["firstChoiceDomain"]
        == data["secondChoiceDomain"]
    ):

        return {
            "status": "error",
            "message": (
                "First and second choice domains "
                "must be different"
            )
        }, 400

    # =====================================================
    # CHECK DUPLICATE APPLICATION
    # =====================================================

    existing_application = (
        applications_collection.find_one(
            {
                "email": data["email"]
            }
        )
    )

    if existing_application:

        return {
            "status": "error",
            "message": (
                "An application with this email "
                "already exists"
            )
        }, 409

    # =====================================================
    # SAVE APPLICATION
    # =====================================================

    try:

        application = {
            **data,
            "status": "submitted",
            "submittedAt": datetime.now()
        }

        result = applications_collection.insert_one(
            application
        )

    except Exception:

        return {
            "status": "error",
            "message": "Failed to save application"
        }, 500

    # =====================================================
    # CONSUME EMAIL VERIFICATION
    # =====================================================

    del verified_emails[data["email"]]

    # =====================================================
    # SEND APPLICATION CONFIRMATION EMAIL
    # =====================================================

    application_id = str(
        result.inserted_id
    )

    email_sent = (
        send_application_confirmation_email(
            recipient_email=data["email"],
            applicant_name=data["fullName"],
            application_id=application_id
        )
    )

    # The application is already safely stored.
    # Email failure must not make the application
    # appear to have failed.

    return {
        "status": "success",
        "message": "Application received",
        "applicationId": application_id,
        "emailSent": email_sent
    }, 201


# =========================================================
# GET ALL APPLICATIONS
# ADMIN ONLY
# =========================================================

@app.get("/api/applications")
@admin_required
def get_applications():

    try:

        applications = list(
            applications_collection.find(
                {},
                {
                    "_id": 1,
                    "fullName": 1,
                    "email": 1,
                    "department": 1,
                    "yearOfStudy": 1,
                    "firstChoiceDomain": 1,
                    "secondChoiceDomain": 1,
                    "status": 1,
                    "submittedAt": 1
                }
            )
        )

        for application in applications:

            application["_id"] = str(
                application["_id"]
            )

        return {
            "status": "success",
            "applications": applications
        }, 200

    except Exception:

        return {
            "status": "error",
            "message": "Failed to fetch applications"
        }, 500


# =========================================================
# GET SINGLE APPLICATION
# ADMIN ONLY
# =========================================================

@app.get("/api/applications/<application_id>")
@admin_required
def get_application(application_id):

    # Check valid MongoDB ObjectId
    if not ObjectId.is_valid(
        application_id
    ):

        return {
            "status": "error",
            "message": "Invalid application ID"
        }, 400

    try:

        application = (
            applications_collection.find_one(
                {
                    "_id": ObjectId(application_id)
                }
            )
        )

        if not application:

            return {
                "status": "error",
                "message": "Application not found"
            }, 404

        # ObjectId is not directly JSON serializable
        application["_id"] = str(
            application["_id"]
        )

        return {
            "status": "success",
            "application": application
        }, 200

    except Exception:

        return {
            "status": "error",
            "message": "Failed to fetch application"
        }, 500


# =========================================================
# SELECT APPLICANT
# ADMIN ONLY
# =========================================================

@app.post(
    "/api/applications/<application_id>/select"
)
@admin_required
def select_application(application_id):

    # -----------------------------------------------------
    # VALIDATE APPLICATION ID
    # -----------------------------------------------------

    if not ObjectId.is_valid(
        application_id
    ):

        return {
            "status": "error",
            "message": "Invalid application ID"
        }, 400

    object_id = ObjectId(
        application_id
    )

    try:

        # -------------------------------------------------
        # FIND APPLICATION
        # -------------------------------------------------

        application = (
            applications_collection.find_one(
                {
                    "_id": object_id
                }
            )
        )

        if not application:

            return {
                "status": "error",
                "message": "Application not found"
            }, 404

        # -------------------------------------------------
        # PREVENT DUPLICATE SELECTION
        # -------------------------------------------------

        if application.get("status") == "selected":

            return {
                "status": "error",
                "message": (
                    "This applicant has already "
                    "been selected."
                )
            }, 409

        # -------------------------------------------------
        # GET APPLICANT DETAILS
        # -------------------------------------------------

        applicant_email = application.get(
            "email"
        )

        applicant_name = application.get(
            "fullName",
            "Applicant"
        )

        if not applicant_email:

            return {
                "status": "error",
                "message": (
                    "Applicant email is missing."
                )
            }, 400

        # -------------------------------------------------
        # SEND SELECTION EMAIL
        # -------------------------------------------------

        email_sent = send_selection_email(
            recipient_email=applicant_email,
            applicant_name=applicant_name
        )

        # -------------------------------------------------
        # DO NOT SELECT IF EMAIL FAILED
        # -------------------------------------------------

        if not email_sent:

            return {
                "status": "error",
                "message": (
                    "Selection email could not be sent. "
                    "Applicant was not marked as selected."
                )
            }, 502

        # -------------------------------------------------
        # UPDATE APPLICATION STATUS
        # -------------------------------------------------

        result = (
            applications_collection.update_one(
                {
                    "_id": object_id,
                    "status": {
                        "$ne": "selected"
                    }
                },
                {
                    "$set": {
                        "status": "selected",
                        "selectionEmailSent": True,
                        "selectionEmailSentAt": (
                            datetime.now()
                        )
                    }
                }
            )
        )

        if result.modified_count == 0:

            return {
                "status": "error",
                "message": (
                    "Applicant status could not "
                    "be updated."
                )
            }, 500

        return {
            "status": "success",
            "message": (
                "Applicant selected and selection "
                "email sent successfully."
            ),
            "newStatus": "selected"
        }, 200

    except Exception as e:

        print(
            "Selection error:",
            str(e)
        )

        return {
            "status": "error",
            "message": "Failed to select applicant."
        }, 500


# =========================================================
# UPDATE APPLICATION STATUS
# ADMIN ONLY
# =========================================================

@app.patch(
    "/api/applications/<application_id>/status"
)
@admin_required
def update_application_status(
    application_id
):

    # Validate ObjectId
    if not ObjectId.is_valid(
        application_id
    ):

        return {
            "status": "error",
            "message": "Invalid application ID"
        }, 400

    data = request.get_json()

    if not data:

        return {
            "status": "error",
            "message": "Request body is required"
        }, 400

    new_status = data.get(
        "status"
    )

    allowed_statuses = [
        "submitted",
        "shortlisted",
        "selected",
        "rejected"
    ]

    if new_status not in allowed_statuses:

        return {
            "status": "error",
            "message": "Invalid application status"
        }, 400

    try:

        result = (
            applications_collection.update_one(
                {
                    "_id": ObjectId(
                        application_id
                    )
                },
                {
                    "$set": {
                        "status": new_status
                    }
                }
            )
        )

        if result.matched_count == 0:

            return {
                "status": "error",
                "message": "Application not found"
            }, 404

        return {
            "status": "success",
            "message": (
                "Application status updated"
            ),
            "newStatus": new_status
        }, 200

    except Exception:

        return {
            "status": "error",
            "message": (
                "Failed to update application status"
            )
        }, 500


# =========================================================
# EXPORT APPLICATIONS TO EXCEL
# ADMIN ONLY
# =========================================================

@app.get(
    "/api/admin/applications/export"
)
@admin_required
def export_applications():

    try:

        applications = list(
            applications_collection.find({})
        )

        # Create workbook
        workbook = Workbook()

        sheet = workbook.active

        sheet.title = "Applications"

        # Excel headers
        headers = [
            "Application ID",
            "Full Name",
            "Email",
            "Phone Number",
            "Gender",
            "Department",
            "Year of Study",
            "Roll Number",
            "First Choice Domain",
            "Why First Choice",
            "Second Choice Domain",
            "Why Second Choice",
            "Why Join FSW",
            "Skills & Experience",
            "Academic Balance",
            "Status",
            "Submitted At"
        ]

        sheet.append(
            headers
        )

        # Add application data
        for application in applications:

            sheet.append([
                str(
                    application.get(
                        "_id",
                        ""
                    )
                ),

                application.get(
                    "fullName",
                    ""
                ),

                application.get(
                    "email",
                    ""
                ),

                application.get(
                    "phoneNumber",
                    ""
                ),

                application.get(
                    "gender",
                    ""
                ),

                application.get(
                    "department",
                    ""
                ),

                application.get(
                    "yearOfStudy",
                    ""
                ),

                application.get(
                    "rollNumber",
                    ""
                ),

                application.get(
                    "firstChoiceDomain",
                    ""
                ),

                application.get(
                    "whyFirstChoice",
                    ""
                ),

                application.get(
                    "secondChoiceDomain",
                    ""
                ),

                application.get(
                    "whySecondChoice",
                    ""
                ),

                application.get(
                    "whyJoinFSW",
                    ""
                ),

                application.get(
                    "skillsAndExperience",
                    ""
                ),

                application.get(
                    "academicBalance",
                    ""
                ),

                application.get(
                    "status",
                    ""
                ),

                application.get(
                    "submittedAt",
                    ""
                )
            ])

        # Store Excel file in memory
        output = BytesIO()

        workbook.save(
            output
        )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="FSW_Applications.xlsx",
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )

    except Exception:

        return {
            "status": "error",
            "message": (
                "Failed to export applications"
            )
        }, 500


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run()
