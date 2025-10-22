
from __future__ import annotations
import os
import io
import sys
import yaml
from dataclasses import dataclass
from typing import List, Tuple, Optional

import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageOps

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


THEMES = {
    "Dark": {
        "bg": "#202225",
        "button_fg": "#333333",
        "button_hover": "#444444",
        "button_text": "#ffffff",
        "label_text": "#cccccc",
        "accent_pixelate": "#00d1b2",
        "accent_black": "#ff5555",
    },
    "Light": {
        "bg": "#eeeeee",
        "button_fg": "#dddddd",
        "button_hover": "#cccccc",
        "button_text": "#111111",
        "label_text": "#333333",
        "accent_pixelate": "#00a896",
        "accent_black": "#cc0000",
    },
    "Monochrome": {
        "bg": "#1a1a1a",
        "button_fg": "#2d2d2d",
        "button_hover": "#3c3c3c",
        "button_text": "#e0e0e0",
        "label_text": "#b3b3b3",
        "accent_pixelate": "#808080",
        "accent_black": "#e0e0e0",
    }
}



SETTINGS_PATH = os.path.join(os.getcwd(), "settings.yml")

DEFAULT_SETTINGS = {
    "theme": "Dark",
    "mode": "Pixelate",
    "pixel": 12
}



def load_settings():
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or DEFAULT_SETTINGS.copy()
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings: dict):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(settings, f, sort_keys=False)
    except Exception as e:
        print(f"[WARN] Failed to save settings: {e}")


@dataclass
class PendingBox:
    rect: Tuple[int, int, int, int]  # in *image* coordinates: (x1, y1, x2, y2)
    mode: str                        # "black" or "pixelate"
    canvas_id: Optional[int] = None  # handle of preview rectangle on canvas


class RedaxApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        set_icons(self)
        
        self.title("Redax Mini")
        self.geometry("1100x700")
        # self.minsize(920, 600)

        # State
        self.image: Optional[Image.Image] = None         # original image in RGBA
        self.image_path: Optional[str] = None
        self.display_image: Optional[Image.Image] = None # resized for current zoom
        self.display_tk: Optional[ImageTk.PhotoImage] = None
        self.zoom: float = 1.0
        self.fit_scale: float = 1.0
        self.pending: List[PendingBox] = []              # boxes not yet burned
        self.undo_stack: List[Image.Image] = []          # past burned images
        self.redo_stack: List[Image.Image] = []
        self.draw_start: Optional[Tuple[int, int]] = None
        self.temp_rect_id: Optional[int] = None

        self.settings = load_settings()
        save_settings(self.settings)

        self.mode = self.settings.get("mode", "black")
        self.pixel_size = self.settings.get("pixel", 12)
        self.active_theme = THEMES.get(self.settings.get("theme", "Dark"), THEMES["Dark"])

        self._build_ui()

        # Sync UI state to loaded settings
        self.mode_var.set(self.mode)
        self.theme_var.set(self.settings.get("theme", "Dark"))
        self.pixel_slider.set(self.pixel_size)
        
        # Update the pixel label to the correct size
        self.pixel_lbl.configure(text=f"Pixel {self.pixel_size}")

        # Trigger correct UI enable/disable state for mode
        self.on_mode_change(self.mode)

        # Apply the saved theme visually
        self.on_theme_change(self.settings.get("theme", "Dark"))

        self._bind_keys()
        
        
        self.attributes('-alpha', 0.0)
        self.after(10, self.fade_in)

    def fade_in(self, step=0.05):
        alpha = self.attributes('-alpha')
        if alpha < 1.0:
            alpha += step
            self.attributes('-alpha', alpha)
            self.after(10, self.fade_in, step)
                

    # --------------------------- UI ---------------------------
    def _build_ui(self):
        # Top toolbar
        tb = ctk.CTkFrame(self)
        tb.pack(side="top", fill="x", padx=6, pady=(6, 4))

        self.btn_open = ctk.CTkButton(tb, text="▲", command=self.on_open, width = 40)
        self.btn_open.pack(side="left", padx=4)

        self.btn_save = ctk.CTkButton(tb, text="▼", command=self.on_save, width = 40, state="disabled")
        self.btn_save.pack(side="left", padx=4)
        
        

        self.btn_undo = ctk.CTkButton(tb, text="◄", command=self.on_undo, width = 40, state="disabled")
        self.btn_undo.pack(side="left", padx=4)

        self.btn_redo = ctk.CTkButton(tb, text="►", command=self.on_redo, width = 40, state="disabled")
        self.btn_redo.pack(side="left", padx=4)

        

        # Mode selector
        self.mode_lbl = ctk.CTkLabel(tb, text="Mode:")
        self.mode_lbl.pack(side="left", padx=(18, 4))

        self.mode_var = tk.StringVar(value=self.mode)
        self.opt_mode = ctk.CTkOptionMenu(tb, variable=self.mode_var,
                                          values=["black", "pixelate"],
                                          command=self.on_mode_change)
        self.opt_mode.pack(side="left", padx=4)

        # Pixel size slider (for pixelate)
        self.pixel_slider = ctk.CTkSlider(tb, from_=4, to=48, number_of_steps=11, command=self.on_pixel_change)
        self.pixel_slider.set(self.pixel_size)
        self.pixel_slider.pack(side="left", padx=8)
        self.pixel_lbl = ctk.CTkLabel(tb, text=f"Pixel {self.pixel_size}")
        self.pixel_lbl.pack(side="left")
        
        self.pixel_slider.configure(state="disabled")
        self.pixel_lbl.configure(text="Pixel (N/A)", text_color="gray")



        # Zoom controls
        self.zoom_lbl = ctk.CTkLabel(tb, text="Zoom:")
        self.zoom_lbl.pack(side="left", padx=(18, 4))
        self.zoom_slider = ctk.CTkSlider(tb, from_=25, to=300, number_of_steps=55, command=self.on_zoom_change)
        self.zoom_slider.set(100)
        self.zoom_slider.pack(side="left", padx=4, fill="x", expand=True)

        # Canvas area
        self.canvas = tk.Canvas(self, bg="#202225", highlightthickness=0)
        self.canvas.pack(side="top", fill="both", expand=True, padx=6, pady=(0, 6))

        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<Configure>", lambda e: self._render())
        self.canvas.bind("<MouseWheel>", self.on_wheel)

        # ---------------- Status and Bottom Controls ----------------
        status_bar = ctk.CTkFrame(self, fg_color="transparent")
        status_bar.pack(side="bottom", fill="x", padx=6, pady=(0, 6))

        # Left side: status label
        self.status = ctk.CTkLabel(status_bar, text="Open an image to begin.")
        self.status.pack(side="left")

        # Right side: burn + theme controls
        right_bar = ctk.CTkFrame(status_bar, fg_color="transparent")
        right_bar.pack(side="right")

        self.btn_burn = ctk.CTkButton(right_bar, text="Burn (Space)", command=self.on_burn, state="disabled")
        self.btn_burn.pack(side="left", padx=8)

        theme_lbl = ctk.CTkLabel(right_bar, text="Theme:")
        theme_lbl.pack(side="left", padx=(12, 4))

        self.theme_var = tk.StringVar(value="Dark")
        self.opt_theme = ctk.CTkOptionMenu(right_bar, variable=self.theme_var, width = 100,
                                           values=list(THEMES.keys()),
                                           command=self.on_theme_change)
        self.opt_theme.pack(side="left")

            
    def cycle_theme(self, direction: int = 1):
        """Cycle through available themes based on current settings."""
        theme_names = list(THEMES.keys())

        # Get current theme name from settings (or default to Dark)
        current_theme = self.settings.get("theme", "Dark")

        try:
            index = theme_names.index(current_theme)
        except ValueError:
            index = 0

        # Move forward or backward and wrap around
        new_index = (index + direction) % len(theme_names)
        new_theme = theme_names[new_index]

        # Apply it through the existing handler (so UI + save logic are consistent)
        self.theme_var.set(new_theme)
        self.on_theme_change(new_theme)

        # Optional: flash theme name briefly
        self.status.configure(text=f"Theme: {new_theme}")
        self.after(2000, lambda: self.status.configure(text=""))


            
    def on_theme_change(self, value):
        """Apply a new theme from the THEMES dictionary."""
        theme = THEMES.get(value, THEMES["Dark"])
        self.active_theme = theme  # store active theme for later use (e.g. in _render)

        # ---- Main surfaces ----
        self.configure(fg_color=theme["bg"])
        self.canvas.configure(bg=theme["bg"])

        # ---- Buttons ----
        buttons = [self.btn_open, self.btn_save, self.btn_undo,
                   self.btn_redo, self.btn_burn]
        for btn in buttons:
            btn.configure(fg_color=theme["button_fg"],
                          hover_color=theme["button_hover"],
                          text_color=theme["button_text"])

        # ---- Labels ----
        labels = [self.pixel_lbl, self.status, self.mode_lbl, self.zoom_lbl]
        for lbl in labels:
            lbl.configure(text_color=theme["label_text"])


        # ---- Sliders ----
        sliders = [self.pixel_slider, self.zoom_slider]
        for s in sliders:
            s.configure(progress_color=theme["accent_pixelate"],
                        button_color=theme["button_fg"],
                        button_hover_color=theme["button_hover"])

        # ---- Option menus (mode + theme selector) ----
        option_menus = [self.opt_mode, self.opt_theme]
        for om in option_menus:
            om.configure(fg_color=theme["button_fg"],
                         button_color=theme["button_hover"],
                         text_color=theme["button_text"])

        # ---- Frames (toolbar/status) ----
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                child.configure(fg_color="transparent")

        # ---- Update pixel label based on mode ----
        if self.mode == "pixelate":
            self.pixel_lbl.configure(text=f"Pixel {self.pixel_size}",
                                     text_color=theme["button_text"])
        else:
            self.pixel_lbl.configure(text="Pixel (N/A)",
                                     text_color="gray")

        # ---- Save theme selection (corrected) ----
        self.settings["theme"] = value
        save_settings(self.settings)

        # ---- Re-render to apply new accent colors ----
        self._render()





    def _bind_keys(self):
        self.bind("<Control-s>", lambda e: self.on_save())
        self.bind("<Control-z>", lambda e: self.on_undo())
        self.bind("<Control-y>", lambda e: self.on_redo())
        self.bind("<Control-t>", lambda e: self.cycle_theme(1)) 
        self.bind("<Control-Shift-T>", lambda e: self.cycle_theme(-1))  
        self.bind("<space>", lambda e: self.on_burn())
        self.bind("b", lambda e: self._set_mode("black"))
        self.bind("p", lambda e: self._set_mode("pixelate"))
        self.bind("-", lambda e: self._nudge_zoom(-10))
        self.bind("=", lambda e: self._nudge_zoom(10))

    # ----------------------- File ops -------------------------
    def on_open(self):
        ftypes = [
            ("Images", "*.png *.jpg *.jpeg *.webp *.bmp"),
            ("PNG", "*.png"),
            ("JPEG", "*.jpg *.jpeg"),
            ("WEBP", "*.webp"),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(title="Open image", filetypes=ftypes)
        if not path:
            return
        try:
            img = Image.open(path)
            # Convert to RGBA to simplify drawing; also remove orientation EXIF by transposing
            img = ImageOps.exif_transpose(img).convert("RGBA")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{e}")
            return

        self.image = img
        self.image_path = path
        self.pending.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._update_controls()
        self._fit_to_canvas()

        # --- New: Fade-in the rendered image ---
        self._fade_in_render(img)

        self.status.configure(
            text=f"Loaded: {os.path.basename(path)} | {self.image.width}×{self.image.height}"
        )

    def _fade_in_render(self, pil_image, steps=10, delay=10):
        """Smoothly fade in a PIL image on the canvas, without black showing through transparency."""
        if not hasattr(self, "canvas"):
            return

        # Grab theme background colour
        bg_hex = self.active_theme["bg"].lstrip("#")
        bg_rgb = tuple(int(bg_hex[i:i+2], 16) for i in (0, 2, 4))

        # Prepare image scaled to current zoom
        display_img = pil_image.resize(
            (int(pil_image.width * self.fit_scale),
             int(pil_image.height * self.fit_scale)),
            Image.Resampling.LANCZOS
        ).convert("RGBA")

        # Clear existing content once
        self.canvas.delete("all")

        # --- Fade animation ---
        for i in range(steps + 1):
            alpha = int(255 * (i / steps))

            # Create the intermediate alpha frame
            frame = display_img.copy()
            frame.putalpha(alpha)

            # Flatten onto theme background BEFORE sending to Tk
            base = Image.new("RGBA", frame.size, bg_rgb + (255,))
            composited = Image.alpha_composite(base, frame).convert("RGB")

            # Draw on canvas
            tk_img = ImageTk.PhotoImage(composited)
            self.display_tk = tk_img
            self.canvas.create_image(
                self.canvas.winfo_width() // 2,
                self.canvas.winfo_height() // 2,
                image=tk_img,
                anchor="center",
                tags="img",
            )

            self.update_idletasks()
            self.after(delay)

        # --- Final opaque render to guarantee proper background ---
        self.canvas.delete("img")
        final_base = Image.new("RGBA", display_img.size, bg_rgb + (255,))
        final_composite = Image.alpha_composite(final_base, display_img).convert("RGB")
        self.display_tk = ImageTk.PhotoImage(final_composite)
        self.canvas.create_image(
            self.canvas.winfo_width() // 2,
            self.canvas.winfo_height() // 2,
            image=self.display_tk,
            anchor="center",
            tags="img",
        )

        self.update_idletasks()




    def on_save(self):
        if self.image is None:
            return
        initial = self._suggest_output_name()
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile=initial,
                                            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg"), ("All", "*.*")])
        if not path:
            return
        try:
            # STRIP metadata by writing fresh image data without EXIF/ICC
            out = self.image
            if path.lower().endswith(('.jpg', '.jpeg')):
                # Convert to RGB for JPEG (no alpha); write without EXIF
                out = out.convert("RGB")
                out.save(path, format="JPEG", quality=95, optimize=True)
            else:
                out.save(path, format="PNG", optimize=True)
            self.status.configure(text=f"Saved: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file:\n{e}")

    def _suggest_output_name(self) -> str:
        if not self.image_path:
            return "redacted.png"
        stem, ext = os.path.splitext(os.path.basename(self.image_path))
        return f"{stem}.redacted.png"

    # ------------------------ Zoom ----------------------------
    def on_zoom_change(self, value):
        self.zoom = float(value) / 100.0
        self._render()

    def _nudge_zoom(self, delta_percent: int):
        val = max(25, min(300, int(self.zoom * 100) + delta_percent))
        self.zoom_slider.set(val); self.on_zoom_change(val)

    def _fit_to_canvas(self):
        if not self.image:
            return
        cw = max(1, self.canvas.winfo_width()); ch = max(1, self.canvas.winfo_height())
        if cw < 2 or ch < 2:
            # Canvas not laid out yet; defer
            self.after(50, self._fit_to_canvas)
            return
        sx = cw / self.image.width; sy = ch / self.image.height
        self.fit_scale = min(sx, sy)
        self.zoom = 1.0
        self.zoom_slider.set(100)
        self._render()

    # ----------------------- Rendering ------------------------
    def _render(self):
        self.canvas.delete("all")
        if not self.image:
            return
        # Compose display image
        scale = self.fit_scale * self.zoom
        w = max(1, int(self.image.width * scale))
        h = max(1, int(self.image.height * scale))
        self.display_image = self.image.resize((w, h), Image.NEAREST)
        self.display_tk = ImageTk.PhotoImage(self.display_image)

        # Center in canvas
        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        x = (cw - w) // 2; y = (ch - h) // 2
        self.canvas.create_image(x, y, anchor="nw", image=self.display_tk, tags=("img",))

        # Re-draw pending boxes overlaid (scaled to current zoom)
        for box in self.pending:
            cx1, cy1 = self._img_to_canvas(box.rect[0], box.rect[1])
            cx2, cy2 = self._img_to_canvas(box.rect[2], box.rect[3])
            color = "#00d1b2" if box.mode == "pixelate" else "#ff5555"
            box.canvas_id = self.canvas.create_rectangle(cx1, cy1, cx2, cy2, outline=color, width=2)

    # ----------------------- Mouse ops ------------------------
    def on_mouse_down(self, event):
        if not self.image:
            return
        self.draw_start = (event.x, event.y)
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id); self.temp_rect_id = None

    def on_mouse_drag(self, event):
        if not self.image or not self.draw_start:
            return
        x1, y1 = self.draw_start
        x2, y2 = event.x, event.y
        if self.temp_rect_id:
            self.canvas.coords(self.temp_rect_id, x1, y1, x2, y2)
        else:
            color = "#00d1b2" if self.mode == "pixelate" else "#ff5555"
            self.temp_rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2, dash=(4,2))

    def on_mouse_up(self, event):
        if not self.image or not self.draw_start:
            return
        x1, y1 = self.draw_start
        x2, y2 = event.x, event.y
        self.draw_start = None
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id); self.temp_rect_id = None
        # Convert canvas rect to image coordinates
        ix1, iy1 = self._canvas_to_img(x1, y1)
        ix2, iy2 = self._canvas_to_img(x2, y2)
        # Clamp and normalise
        x1i, x2i = sorted((max(0, min(self.image.width, ix1)), max(0, min(self.image.width, ix2))))
        y1i, y2i = sorted((max(0, min(self.image.height, iy1)), max(0, min(self.image.height, iy2))))
        if x2i - x1i < 2 or y2i - y1i < 2:
            return
        pb = PendingBox(rect=(x1i, y1i, x2i, y2i), mode=self.mode)
        self.pending.append(pb)
        self._update_controls(); self._render()

    # ------------------------ Actions -------------------------
    def on_burn(self):
        if not self.image or not self.pending:
            return
        # Push to undo stack (copy image to preserve state)
        self.undo_stack.append(self.image.copy())
        self.redo_stack.clear()

        draw = ImageDraw.Draw(self.image)
        for box in self.pending:
            x1, y1, x2, y2 = box.rect
            if box.mode == "black":
                draw.rectangle([x1, y1, x2, y2], fill=(0,0,0,255))
            else:
                # Pixelate region deterministically by block size
                region = self.image.crop((x1, y1, x2, y2))
                w, h = region.size
                k = max(1, int(min(w, h) // max(4, self.pixel_size)))
                small = region.resize((max(1, w // k), max(1, h // k)), Image.NEAREST)
                pix = small.resize((w, h), Image.NEAREST)
                self.image.paste(pix, (x1, y1))
        self.pending.clear()
        self._update_controls(); self._render()
        self.status.configure(text=f"Burned redactions. Undo available (Ctrl+Z)")

    def on_undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.image.copy())
        self.image = self.undo_stack.pop()
        self.pending.clear()
        self._update_controls(); self._render()

    def on_redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.image.copy())
        self.image = self.redo_stack.pop()
        self.pending.clear()
        self._update_controls(); self._render()

    def on_mode_change(self, value):
        if value == "pixelate":
            self.pixel_slider.configure(state="normal")
            self.pixel_lbl.configure(text=f"Pixel {self.pixel_size}", text_color="white")
        else:
            self.pixel_slider.configure(state="disabled")
            self.pixel_lbl.configure(text="Pixel (N/A)", text_color="gray")

        self.settings["mode"] = value
        save_settings(self.settings)
        self._set_mode(value)



    def _set_mode(self, mode: str):
        if mode not in ("black", "pixelate"):
            return
        self.mode = mode
        self.mode_var.set(mode)
        self._render()

    def on_pixel_change(self, value):
        self.pixel_size = int(float(value))
        self.pixel_lbl.configure(text=f"Pixel {self.pixel_size}")
        
        self.settings["pixel"] = self.pixel_size
        save_settings(self.settings)

    # ----------------------- Utilities ------------------------
    def _img_to_canvas(self, ix: int, iy: int) -> Tuple[int, int]:
        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        scale = self.fit_scale * self.zoom
        w = int(self.image.width * scale); h = int(self.image.height * scale)
        ox = (cw - w) // 2; oy = (ch - h) // 2
        cx = int(ox + ix * scale); cy = int(oy + iy * scale)
        return cx, cy

    def _canvas_to_img(self, cx: int, cy: int) -> Tuple[int, int]:
        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        scale = self.fit_scale * self.zoom
        w = int(self.image.width * scale); h = int(self.image.height * scale)
        ox = (cw - w) // 2; oy = (ch - h) // 2
        ix = int((cx - ox) / scale); iy = int((cy - oy) / scale)
        return ix, iy

    def _update_controls(self):
        has_img = self.image is not None
        self.btn_burn.configure(state=("normal" if (has_img and self.pending) else "disabled"))
        self.btn_save.configure(state=("normal" if has_img else "disabled"))
        self.btn_undo.configure(state=("normal" if self.undo_stack else "disabled"))
        self.btn_redo.configure(state=("normal" if self.redo_stack else "disabled"))

    def on_wheel(self, event):
        if not self.image:
            return
        delta = 10 if event.delta > 0 else -10
        self._nudge_zoom(delta)


def get_resource_path(relative_path: str) -> str:
    """Return path that works in both script and frozen exe."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # Running as a bundled exe
        base_path = sys._MEIPASS
    else:
        # Running as a normal .py script
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def set_icons(window):
    try:
        icon16 = tk.PhotoImage(file=get_resource_path("resources/icon16.png"))
        icon32 = tk.PhotoImage(file=get_resource_path("resources/icon32.png"))
        window.iconphoto(True, icon16, icon32)
    except Exception as e:
        print(f"Could not set icon: {e}")


if __name__ == "__main__":
    app = RedaxApp()
    app.mainloop()
