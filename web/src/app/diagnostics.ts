export type Diagnostic = { at: string; event: string; detail?: Record<string, unknown> };

export class Diagnostics {
  readonly events: Diagnostic[];

  constructor() {
    try {
      this.events = JSON.parse(
        localStorage.getItem('adaptive-pa-diagnostics') ?? '[]',
      ) as Diagnostic[];
    } catch {
      this.events = [];
    }
  }

  log(event: string, detail?: Record<string, unknown>): void {
    const entry = { at: new Date().toISOString(), event, detail };
    this.events.push(entry);
    if (this.events.length > 300) this.events.shift();
    try {
      localStorage.setItem('adaptive-pa-diagnostics', JSON.stringify(this.events));
    } catch {
      /* diagnostics remain available in this tab */
    }
    console.info('[adaptive-pa]', event, detail ?? '');
  }

  download(server: unknown): void {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            browser: {
              userAgent: navigator.userAgent,
              platform: navigator.platform,
              location: location.origin,
            },
            events: this.events,
            server,
          },
          null,
          2,
        ),
      ],
      { type: 'application/json' },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `adaptive-pa-diagnostics-${new Date().toISOString().replaceAll(':', '-')}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
