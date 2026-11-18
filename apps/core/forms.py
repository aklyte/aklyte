from django import forms
from .models import Category, Product

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "slug", "description", "icon_class", "sort_order", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "slug", "category", "short_description", "description",
            "price", "discount_price", "thumbnail", "github_repo_owner",
            "github_repo_name", "languages", "frameworks", "database",
            "skill_level", "version", "installation_instructions",
            "documentation_url", "features", "whats_included", "support_details",
            "status", "is_featured",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "installation_instructions": forms.Textarea(attrs={"rows": 4}),
            "features": forms.Textarea(attrs={"rows": 4, "placeholder": "One feature per line"}),
            "whats_included": forms.Textarea(attrs={"rows": 3}),
            "support_details": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        price = cleaned.get("price")
        discount = cleaned.get("discount_price")
        if price is not None and discount is not None and discount >= price:
            self.add_error("discount_price", "Discount price must be lower than regular price.")
        return cleaned
    def save(self, commit=True):
        product = super().save(commit=False)

        if commit:
            product.save()
            self.save_m2m()

            if product.category.slug == "django-projects":
                python_category = Category.objects.filter(
                    slug="python-projects"
                ).first()

                if python_category:
                    product.additional_categories.add(python_category)

            elif product.category.slug == "machine-learning":
                ai_category = Category.objects.filter(
                    slug="ai-projects"
                ).first()

                if ai_category:
                    product.additional_categories.add(ai_category)

        return product


from django.core.exceptions import ValidationError
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from .models import ProductScreenshot

MAX_IMAGE_SIZE = 3 * 1024 * 1024
MAX_PDF_SIZE = 20 * 1024 * 1024

def validate_image_upload(value):
    if value.size > MAX_IMAGE_SIZE:
        raise ValidationError("Image must be 3 MB or smaller.")
    from PIL import Image
    try:
        value.seek(0)
        im = Image.open(value)
        im.verify()
        if im.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError("Unsupported image format")
    except Exception:
        raise ValidationError("Upload a valid JPG, PNG or WebP image.")
    finally:
        value.seek(0)

def validate_pdf_upload(value):
    if value.size > MAX_PDF_SIZE:
        raise ValidationError("PDF must be 20 MB or smaller.")
    value.seek(0)
    header = value.read(5)
    value.seek(0)
    if header != b"%PDF-":
        raise ValidationError("Upload a valid PDF file.")

class CustomerRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, required=False)
    class Meta:
        model = User
        fields = ["username", "email", "first_name", "password1", "password2"]
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name"]

class ScreenshotForm(forms.ModelForm):
    class Meta:
        model = ProductScreenshot
        fields = ["image", "caption", "sort_order"]
    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image: validate_image_upload(image)
        return image

# Additional product validation applied to existing ModelForm.
_original_product_clean = ProductForm.clean
def _product_clean(self):
    cleaned = _original_product_clean(self)
    thumb = cleaned.get("thumbnail")
    if thumb: validate_image_upload(thumb)
    if cleaned.get("status") == "published":
        required = ["name", "category", "description", "short_description", "thumbnail", "github_repo_owner", "github_repo_name", "version"]
        for field in required:
            if not cleaned.get(field) and not (self.instance.pk and getattr(self.instance,field,None)):
                self.add_error(field, "Required to publish this product.")
        if cleaned.get("github_repo_owner") != "aklyte-tech":
            self.add_error("github_repo_owner", "Repository owner must be aklyte-tech.")
    return cleaned
ProductForm.clean = _product_clean
