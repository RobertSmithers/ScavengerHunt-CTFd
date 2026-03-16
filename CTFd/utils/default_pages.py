def build_golden_web_2026_homepage(banner_src):
    return f"""
<link rel=\"stylesheet\" href=\"/themes/core/static/css/golden-web-home.css\" />

<section class=\"gw-home\" aria-label=\"Golden Web 2026 homepage\">
    <article class=\"gw-card\">
        <div class=\"gw-card-inner\">
            <img class=\"gw-logo\" src=\"{banner_src}\" alt=\"Golden Web 2026 banner\" />
            <h1 class=\"gw-title\">Golden Web 2026</h1>
            <p class=\"gw-subtitle\">
                The annual Squadron vs Squadron competition of strength, endurance, and strategy.
            </p>
            <div class=\"gw-cta-wrap\">
                <a class=\"gw-cta\" href=\"/register\">
                    Register now
                </a>
            </div>
            <p class=\"gw-footer-note\">Developed just for you by your favorite developers in the group!</p>
                
        </div>
    </article>
</section>
"""