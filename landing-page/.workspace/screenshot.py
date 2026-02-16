"""Take screenshots of the landing page at different viewport widths."""
import time
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

def take_screenshots():
    options = Options()
    options.add_argument("--headless")

    service = Service("/snap/bin/geckodriver")
    driver = webdriver.Firefox(options=options, service=service)

    url = "http://localhost:8080/"
    output_dir = "/mnt/c/Users/xteam/IdeaProjects/ai-workflow/landing-page/.workspace/screenshots"

    import os
    os.makedirs(output_dir, exist_ok=True)

    viewports = [
        ("desktop", 1440, 900),
        ("tablet", 768, 1024),
        ("mobile", 375, 812),
    ]

    for name, width, height in viewports:
        driver.set_window_size(width, height)
        driver.get(url)
        time.sleep(2)  # Let animations settle

        # Take viewport screenshot (hero)
        driver.save_screenshot(f"{output_dir}/{name}_hero.png")

        # Scroll through the page and take section screenshots
        sections = [
            ("problems", 800),
            ("solution", 1600),
            ("how-it-works", 2400),
            ("features", 3200),
            ("differentiator", 4000),
            ("pricing", 4800),
            ("faq", 5600),
            ("final-cta", 6400),
        ]

        for section_name, scroll_y in sections:
            driver.execute_script(f"window.scrollTo(0, {scroll_y})")
            time.sleep(0.5)
            driver.save_screenshot(f"{output_dir}/{name}_{section_name}.png")

    # Also take a full-page screenshot at desktop width
    driver.set_window_size(1440, 900)
    driver.get(url)
    time.sleep(2)

    # Get full page height
    page_height = driver.execute_script("return document.body.scrollHeight")
    driver.set_window_size(1440, page_height)
    time.sleep(1)
    driver.save_screenshot(f"{output_dir}/desktop_full_page.png")

    driver.quit()
    print(f"Screenshots saved to {output_dir}")
    print(f"Full page height: {page_height}px")

if __name__ == "__main__":
    take_screenshots()
