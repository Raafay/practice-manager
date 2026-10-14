"""Settings: risk questions, score bands and review intervals, and the practice's AML records."""

from datetime import timedelta

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps import events
from apps.clients.views_base import done, render_form
from apps.core.dates import add_months
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin

from .forms import (
    AmlSettingsForm,
    PolicyDocumentForm,
    PracticeRecordsForm,
    RiskQuestionForm,
    TrainingForm,
)
from .models import AmlSettings, PolicyDocument, RiskQuestion, TrainingRecord


class SettingsMixin(CapabilityRequiredMixin):
    required_rights = ("settings.manage",)


def _describe(question: RiskQuestion) -> dict:
    return {
        "section": question.section,
        "text": question.text,
        "help": question.help_text,
        "options": question.options,
        "records_check": question.records_check,
        "active": question.active,
        "position": question.position,
    }


class QuestionListView(SettingsMixin, View):
    def get(self, request):
        return render(
            request,
            "aml/settings_questions.html",
            {"questions": RiskQuestion.objects.all(), "aml": AmlSettings.load()},
        )


class QuestionEditView(SettingsMixin, View):
    def _question(self, pk):
        return get_object_or_404(RiskQuestion, pk=pk) if pk else None

    def _render(self, request, form, question, status=200):
        return render_form(
            request,
            title="Edit question" if question else "New question",
            form=form,
            action=reverse("aml:question_edit", args=[question.pk])
            if question
            else reverse("aml:question_add"),
            target="drawer",
            status=status,
            intro="Changes apply to new assessments. Past assessments keep the wording and "
            "scores they were answered with.",
        )

    def get(self, request, pk=None):
        question = self._question(pk)
        form = RiskQuestionForm.from_question(question) if question else RiskQuestionForm()
        return self._render(request, form, question)

    def post(self, request, pk=None):
        question = self._question(pk)
        form = RiskQuestionForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, question, 422)
        data = form.cleaned_data
        before = _describe(question) if question else None
        question = question or RiskQuestion()
        question.section = data["section"]
        question.text = data["text"]
        question.help_text = data["help_text"]
        question.answer_type = data["answer_type"]
        question.options = data["options"]
        question.records_check = data["records_check"]
        question.position = data["position"]
        question.active = data["active"]
        question.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} {'changed' if before else 'added'} the risk question "
            f"“{question.text}”.",
            setting="risk question",
            old=before,
            new=_describe(question),
        )
        return done(request, reverse("aml:questions"), "Question saved.")


class QuestionToggleView(SettingsMixin, View):
    def post(self, request, pk):
        question = get_object_or_404(RiskQuestion, pk=pk)
        question.active = not question.active
        question.save(update_fields=["active", "updated_at"])
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} switched {'on' if question.active else 'off'} the risk question "
            f"“{question.text}”.",
            setting="risk question",
        )
        return redirect("aml:questions")


class BandsView(SettingsMixin, View):
    def get(self, request):
        return render(
            request,
            "aml/settings_bands.html",
            {"form": AmlSettingsForm(instance=AmlSettings.load())},
        )

    def post(self, request):
        instance = AmlSettings.load()
        form = AmlSettingsForm(request.POST, instance=instance)
        if not form.is_valid():
            return render(request, "aml/settings_bands.html", {"form": form}, status=422)
        form.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} changed the AML score bands and review intervals.",
            setting="aml bands",
            changed=form.changed_data,
        )
        messages.success(request, "Saved.")
        return redirect("aml:bands")


class RecordsView(SettingsMixin, View):
    """The supervisory body, nominated officer, training log and policy library."""

    def _context(self, **extra):
        aml = AmlSettings.load()
        today = timezone.localdate()
        training = list(TrainingRecord.objects.select_related("person"))
        latest = {}
        for record in training:
            latest.setdefault(record.person_id, record)
        due = [
            r
            for r in latest.values()
            if add_months(r.trained_on, aml.training_reminder_months) <= today + timedelta(days=30)
        ]
        context = {
            "form": PracticeRecordsForm(instance=aml),
            "training": training,
            "training_form": TrainingForm(),
            "policy_form": PolicyDocumentForm(),
            "policies": PolicyDocument.objects.all(),
            "training_due": due,
        }
        context.update(extra)
        return context

    def get(self, request):
        return render(request, "aml/settings_records.html", self._context())

    def post(self, request):
        form = PracticeRecordsForm(request.POST, instance=AmlSettings.load())
        if not form.is_valid():
            return render(
                request, "aml/settings_records.html", self._context(form=form), status=422
            )
        form.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} changed the AML practice records.",
            setting="aml records",
        )
        messages.success(request, "Saved.")
        return redirect("aml:records")


class TrainingAddView(SettingsMixin, View):
    def post(self, request):
        form = TrainingForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "aml/settings_records.html",
                RecordsView()._context(training_form=form),
                status=422,
            )
        record = form.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} logged AML training for {record.person}: {record.course}.",
            setting="aml training",
        )
        messages.success(request, "Training logged.")
        return redirect("aml:records")


class TrainingDeleteView(SettingsMixin, View):
    def post(self, request, pk):
        record = get_object_or_404(TrainingRecord, pk=pk)
        label = str(record)
        record.delete()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} removed the AML training record “{label}”.",
            setting="aml training",
        )
        return redirect("aml:records")


class PolicyAddView(SettingsMixin, View):
    def post(self, request):
        form = PolicyDocumentForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request,
                "aml/settings_records.html",
                RecordsView()._context(policy_form=form),
                status=422,
            )
        upload = form.cleaned_data["file"]
        document = PolicyDocument(
            title=form.cleaned_data["title"],
            original_name=upload.name[:255],
            content_type=form.content_type,
            uploaded_by=request.user,
        )
        document.file.save(upload.name, upload, save=False)
        document.save()
        events.record(
            request.user,
            "document.uploaded",
            f"{request.user} added the AML policy document “{document.title}”.",
            target=document,
        )
        messages.success(request, "Policy document added.")
        return redirect("aml:records")


class PolicyDownloadView(StaffRequiredMixin, View):
    """Policy documents are served through here, never from a public address."""

    def get(self, request, pk):
        document = get_object_or_404(PolicyDocument, pk=pk)
        try:
            handle = document.file.open("rb")
        except OSError:
            raise Http404 from None
        response = FileResponse(
            handle,
            as_attachment=True,
            filename=document.original_name,
            content_type=document.content_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response


class PolicyDeleteView(SettingsMixin, View):
    def post(self, request, pk):
        document = get_object_or_404(PolicyDocument, pk=pk)
        title = document.title
        document.file.delete(save=False)
        document.delete()
        events.record(
            request.user,
            "document.deleted",
            f"{request.user} removed the AML policy document “{title}”.",
        )
        return redirect("aml:records")
