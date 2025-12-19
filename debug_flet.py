
import flet as ft
import sys

print(f"Flet version: {ft.version}")
print(f"Has colors? {hasattr(ft, 'colors')}")

try:
    print(f"ft.colors: {ft.colors}")
except AttributeError as e:
    print(f"Error accessing ft.colors: {e}")

print("Dir(ft):")
print(dir(ft))
