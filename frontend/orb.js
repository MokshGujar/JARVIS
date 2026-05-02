class OrbRenderer {
    constructor(container) {
        this.container = container;
        this.active = false;
        if (!this.container) return;

        this.el = document.createElement('div');
        this.el.className = 'arc-reactor';
        this.el.innerHTML = `
            <div class="reactor-particles"></div>
            <div class="reactor-layer reactor-ticks"></div>
            <div class="reactor-layer reactor-outer"></div>
            <div class="reactor-layer reactor-middle"></div>
            <div class="reactor-layer reactor-inner"></div>
            <div class="reactor-core"></div>
            <div class="reactor-triangle"></div>
        `;
        this.container.replaceChildren(this.el);
    }

    setActive(active) {
        this.active = !!active;
        if (!this.container) return;
        this.container.classList.toggle('active', this.active);
    }

    destroy() {
        if (this.el && this.el.parentNode) this.el.parentNode.removeChild(this.el);
        if (this.container) {
            this.container.classList.remove('active', 'speaking');
        }
    }
}
