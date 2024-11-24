import streamlit as st
from PIL import Image

# App title
st.title("Skin Cancer detection test")

# App description
st.write("Upload your photos and preview them below!")

# File uploader
uploaded_files = st.file_uploader("Choose photos to upload", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

# Display uploaded photos
if uploaded_files:
    st.write("### Uploaded Photos:")
    for uploaded_file in uploaded_files:
        # Open the uploaded file as an image
        image = Image.open(uploaded_file)
        
        # Display the image
        st.image(image, caption=f"Uploaded: {uploaded_file.name}", use_column_width=True)

        # Optional: Save the image if needed
        # image.save(f"saved_images/{uploaded_file.name}")