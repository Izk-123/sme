from django.views.generic import CreateView, ListView


from django.urls import reverse_lazy


from django.contrib import messages


from django.db.models import Sum


from decimal import Decimal


# suppliers/views.py





from django.contrib.auth.mixins import LoginRequiredMixin





from django.views.generic import ListView, DetailView











from core.permissions import OrganizationMixin, RoleRequiredMixin, SubscriptionWriteRequiredMixin





from .forms import SupplierPaymentForm

from .models import Supplier, SupplierPayment









class SupplierMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):





    allowed_roles = ["owner", "accountant"]











    def get_queryset(self):





        return Supplier.objects.filter(organization=self.get_organization()).order_by("name")











class SupplierListView(SupplierMixin, ListView):





    template_name = "suppliers/supplier_list.html"





    context_object_name = "suppliers"





    paginate_by = 20











class SupplierDetailView(SupplierMixin, DetailView):


    model = Supplier


    template_name = "suppliers/supplier_detail.html"


    context_object_name = "supplier"





    def get_queryset(self):


        # Scope to org so /suppliers/<pk>/ can't leak cross-tenant


        return Supplier.objects.filter(organization=self.get_organization())





    def get_context_data(self, **kwargs):


        context = super().get_context_data(**kwargs)





        # ---- Purchases (stock movements) ----


        purchases = (


            self.object.stock_movements


            .filter(movement_type="purchase")


            .select_related("product")


            .order_by("-created_at")


        )


        context["purchases"] = purchases





        # ---- Expenses (services / fees paid to this supplier) ----


        expenses = self.object.expenses.select_related("category").order_by("-date")


        context["expenses"] = expenses





        # ---- Totals ----


        # Stock total uses current product price as a proxy (no cost_price field yet)


        stock_total = sum(


            (Decimal(m.quantity) * Decimal(m.product.price) for m in purchases),


            Decimal("0.00"),


        )


        expense_total = (


            expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")


        )





        context["stock_total"] = stock_total


        context["expense_total"] = expense_total


        context["combined_total"] = stock_total + expense_total


        return context





class SupplierPaymentListView(SupplierMixin, ListView):


    template_name = "suppliers/payment_list.html"


    context_object_name = "payments"


    paginate_by = 20





    def get_queryset(self):


        return (


            SupplierPayment.objects


            .filter(organization=self.get_organization())


            .select_related("supplier")


            .order_by("-date", "-id")


        )








class SupplierPaymentCreateView(SupplierMixin, SubscriptionWriteRequiredMixin, CreateView):


    template_name = "suppliers/payment_form.html"


    form_class = SupplierPaymentForm


    success_url = reverse_lazy("supplier_payment_list")





    def get_form_kwargs(self):


        kwargs = super().get_form_kwargs()


        kwargs["organization"] = self.get_organization()


        return kwargs





    def get_initial(self):


        initial = super().get_initial()


        supplier_id = self.request.GET.get("supplier")


        if supplier_id:


            initial["supplier"] = supplier_id


        return initial





    def form_valid(self, form):


        form.instance.organization = self.get_organization()


        form.instance.created_by = self.request.user


        messages.success(self.request, "Payment recorded.")


        return super().form_valid(form)





