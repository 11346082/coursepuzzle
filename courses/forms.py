from django import forms

from .models import Department, Section, Todo


class SectionTeacherForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ["outline", "announcement", "capacity"]
        widgets = {
            "outline": forms.Textarea(attrs={"rows": 10}),
            "announcement": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_capacity(self):
        cap = self.cleaned_data["capacity"]
        taken = self.instance.enrollments.count()
        if cap < taken:
            raise forms.ValidationError(f"目前已有 {taken} 人修課，人數上限不能低於這個數字")
        return cap


class ProfileForm(forms.Form):
    last_name = forms.CharField(label="姓", max_length=150, required=False)
    first_name = forms.CharField(label="名", max_length=150, required=False)
    department = forms.ModelChoiceField(
        label="系所", queryset=Department.objects.all(), required=False, empty_label="尚未選擇")
    student_no = forms.CharField(label="學號", max_length=20, required=False)


class TodoForm(forms.ModelForm):
    class Meta:
        model = Todo
        fields = ["title", "due_date"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "例如：資料庫期中報告"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }


class ReviewForm(forms.Form):
    rating = forms.ChoiceField(
        label="整體評分", choices=[(5, "5 星 很推薦"), (4, "4 星"), (3, "3 星 普通"), (2, "2 星"), (1, "1 星 不推薦")],
        initial=5)
    comment = forms.CharField(
        label="修課心得", max_length=500, required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "作業量、考試方式、老師風格，寫給下一屆的同學參考"}))
