import streamlit as st
from PIL import Image
import firebase_admin
from firebase_admin import credentials, storage, firestore
import io
import uuid
import joblib
import kaggle
import pickle


# Loading of the model
with open('src/model.pkl', 'rb') as file:
    model = pickle.load(file)
# model = joblib.load('src/model.pkl')
# Firebase setup
# cred = credentials.Certificate("serviceAccountKey.json")  # Replace with your Firebase service account key
# firebase_admin.initialize_app(
#     cred, 
#     {"storageBucket": "gs://skin-cancer-detection-c0570.firebasestorage.app"}  # Replace with your bucket name
# )
# db = firestore.client()
# bucket = storage.bucket()

# # App title
# st.title("Skin Cancer Detection")

# # Description
# st.write("Please upload your photo of the skin deformation!")

# # File uploader
# uploaded_files = st.file_uploader("Choose photos to upload", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

# # Display and upload photos
# if uploaded_files:
#     st.write("### Uploaded Photos:")
#     for uploaded_file in uploaded_files:
#         # Open the uploaded file as an image
#         image = Image.open(uploaded_file)

#         # Display the image
#         st.image(image, caption=f"Uploaded: {uploaded_file.name}", use_column_width=True)

#         # Upload to Firebase
#         if st.button(f"Save {uploaded_file.name} to Firebase"):
#             # Save image to an in-memory buffer
#             buffer = io.BytesIO()
#             image.save(buffer, format="JPEG")
#             buffer.seek(0)

#             # Generate a unique filename
#             unique_filename = f"{uuid.uuid4()}-{uploaded_file.name}"

#             # Upload to Firebase Storage
#             blob = bucket.blob(unique_filename)
#             blob.upload_from_file(buffer, content_type="image/jpeg")
#             blob.make_public()  # Make the file publicly accessible

#             # Save metadata to Firestore
#             doc_ref = db.collection("photos").document(unique_filename)
#             doc_ref.set({
#                 "filename": unique_filename,
#                 "url": blob.public_url,
#                 "uploaded_at": firestore.SERVER_TIMESTAMP,
#             })

#             st.success(f"{uploaded_file.name} has been saved to Firebase!")
#             st.write(f"Access the photo [here]({blob.public_url}).")



