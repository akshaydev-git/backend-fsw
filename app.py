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
import smtplib
from email.message import EmailMessage


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

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD")
SMTP_SENDER_NAME = os.getenv(
    "SMTP_SENDER_NAME",
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
# SHARED VALIDATION HELPERS
# =========================================================

GRIET_EMAIL_PATTERN = r"^[A-Za-z0-9._%+-]+@grietcollege\.com$"


def is_valid_griet_email(email):
    return bool(
        re.fullmatch(
            GRIET_EMAIL_PATTERN,
            email,
            re.IGNORECASE
        )
    )


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
# EMAIL / SMTP HELPERS
# =========================================================
def send_smtp_email(
    receiver_email,
    ottp,
    subject,
    text_content,
    html_content=None
):
    import requests

    url = "https://q1llke7695.execute-api.us-east-1.amazonaws.com/shortit"

    payload = {
        "receiver_email": receiver_email,
        "subject": subject,
        "text_content": text_content,
        "html_content": html_content or ""
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("OTP email request failed:", str(e))
        return False

    print("Status Code:", response.status_code)

    try:
        print("Response Body:", response.json())
    except ValueError:
        print("Response Body (non-JSON):", response.text)

    return response.status_code == 200



def send_otp(receiver_email, otp):


    return send_smtp_email(
        receiver_email=receiver_email,
        ottp=otp,
        subject="Email Verification OTP",
        text_content=(
            f"Your verification OTP is: {otp}\n\n"
            "This OTP expires in 2 minutes."
        )
    )



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

    email = email.strip().lower()

    # Validate GRIET college email format before ever sending an OTP
    if not is_valid_griet_email(email):
        return {
            "status": "error",
            "message": (
                "Please enter your valid GRIET college email address"
            )
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
    # SEND OTP THROUGH GMAIL SMTP
    # =====================================================
    try:

        email_sent = send_otp(
            email,
            otp
        )

        if not email_sent:

            return {
                "status": "error",
                "message": (
                    "Unable to send verification email"
                )
            }, 502

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

    # Normalize OTP to a string so numeric input from the client
    # (e.g. {"otp": 123456} instead of {"otp": "123456"}) still matches
    otp = str(otp).strip()

    # Validate GRIET college email format
    email = email.strip().lower()

    if not is_valid_griet_email(email):
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
    if otp != str(otp_data["otp"]):

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
):
    import requests
    """
    Send a confirmation email after an application
    has been successfully stored in MongoDB.

    """
    url = "https://q1llke7695.execute-api.us-east-1.amazonaws.com/conf"

    payload = {

  "receiver_email":  recipient_email,
  "applicant_name": applicant_name,
  "subject": "FSW Recruitment - Application Screening Update",
  "text_content":  f"Hi {applicant_name},\n\n"

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

    }

    try:
        response = requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Confirmation email request failed:", str(e))
        return False

    print("Status Code:", response.status_code)

    try:
        print("Response Body:", response.json())
    except ValueError:
        print("Response Body (non-JSON):", response.text)

    return response.status_code == 200




# =========================================================
# SEND SELECTION EMAIL
# =========================================================

def send_selection_email(
    recipient_email,
    applicant_name
):
    import requests

    """
    Send a selection email to an applicant who
    has cleared the application screening round.
    """
    url = "https://q1llke7695.execute-api.us-east-1.amazonaws.com/conf"
    whatsapp_group_link="https://chat.whatsapp.com/BRJaYw5pnqy57eNhncNF5R?s=cl&p=a&ilr=0"
    payload = {
    "receiver_email": recipient_email,
    "applicant_name": applicant_name,
    "subject": "FSW Recruitment - You've Been Selected!",
    "text_content": (
        
        f"Dear {applicant_name},\n\n"
        f"🎉 Congratulations! 🥳 We are thrilled to inform you that you have been selected for the offline round for FSW! 🌟 We were very impressed with your background and application.\n\n"
        f"We will reach out shortly with further details and schedule for the offline round. Please join the WhatsApp group using the link below to receive further updates.\n\n"
        f"WhatsApp Group: "https://chat.whatsapp.com/BRJaYw5pnqy57eNhncNF5R?s=cl&p=a&ilr=0"\n\n"
        f"Best regards,\nFSW Team"


      )
      }

    try:
        response = requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Selection email request failed:", str(e))
        return False

    print("Status Code:", response.status_code)

    try:
        print("Response Body:", response.json())
    except ValueError:
        print("Response Body (non-JSON):", response.text)

    return response.status_code == 200




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

    if not is_valid_griet_email(data["email"]):

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

    # Normalize to string first - the client may send this as a number
    phone_number = str(data["phoneNumber"]).strip()

    if not re.fullmatch(
        r"[6-9]\d{9}",
        phone_number
    ):

        return {
            "status": "error",
            "message": (
                "Phone number must contain "
                "exactly 10 digits"
            )
        }, 400

    data["phoneNumber"] = phone_number

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

    # Normalize to int first - the client may send this as a string
    try:
        year_of_study = int(data["yearOfStudy"])
    except (TypeError, ValueError):

        return {
            "status": "error",
            "message": "Invalid year of study"
        }, 400

    if year_of_study not in allowed_years:

        return {
            "status": "error",
            "message": "Invalid year of study"
        }, 400

    data["yearOfStudy"] = year_of_study

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

    # The application is already safely stored, so a failure here
    # (network error, bad gateway response, etc.) must never turn
    # into an unhandled exception / 500 that hides the fact that
    # the application was actually saved successfully.
    try:
        email_sent = send_application_confirmation_email(
            recipient_email=data["email"],
            applicant_name=data["fullName"]
        )
    except Exception as e:
        print("Confirmation email error:", str(e))
        email_sent = False

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
