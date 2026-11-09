from django.contrib import admin

from .models import Ingredient, MenuTest


class IngredientInline(admin.TabularInline):
    model = Ingredient
    extra = 0


@admin.register(MenuTest)
class MenuTestAdmin(admin.ModelAdmin):
    list_display = ("id", "menu_name", "status", "created_at")
    inlines = [IngredientInline]


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ("id", "test", "ingredient_name", "quantity", "unit", "ingredient_cost")
