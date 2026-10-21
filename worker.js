// Serves deckbench/ui under /deckbench/app/: the files are at the top of the folder, so the prefix is taken off the path.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/deckbench/app") {                  // the page's links are relative: it needs the slash
      url.pathname += "/";
      return Response.redirect(url.toString(), 301);
    }
    url.pathname = url.pathname.replace(/^\/deckbench\/app/, "") || "/";
    return env.ASSETS.fetch(new Request(url.toString(), request));
  },
};
