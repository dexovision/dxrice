.pragma library

// Ranking for the application launcher: pure functions, no QML, so the
// ordering is tested on its own (tests/qml/test_launcher.py).

function _words(name) {
    return String(name).toLowerCase().split(/[^a-z0-9]+/).filter(function (w) { return w.length > 0; });
}

// How well `name` matches `query` (both already trimmed): 0 means not at all.
// Returns {score, start, len}: start/len mark the matched run for highlighting
// (len 0 when the match is scattered letters).
function match(name, query) {
    var n = String(name).toLowerCase(), q = String(query).toLowerCase();
    if (!q) return { score: 1, start: 0, len: 0 };
    if (n === q) return { score: 1000, start: 0, len: q.length };
    if (n.indexOf(q) === 0) return { score: 800, start: 0, len: q.length };
    var words = _words(name), pos = 0;
    for (var i = 0; i < words.length; i++) {
        var at = n.indexOf(words[i], pos);
        if (words[i].indexOf(q) === 0 && at >= 0) return { score: 600 - Math.min(i, 5) * 20, start: at, len: q.length };
        pos = at >= 0 ? at + words[i].length : pos;
    }
    var sub = n.indexOf(q);
    if (sub >= 0) return { score: 400, start: sub, len: q.length };
    // letters in order ("ffx" -> "Firefox"): weakest, and only for queries of 2+
    if (q.length >= 2) {
        var j = 0;
        for (var k = 0; k < n.length && j < q.length; k++) if (n[k] === q[j]) j++;
        if (j === q.length) return { score: 150, start: 0, len: 0 };
    }
    return { score: 0, start: 0, len: 0 };
}

// apps: [{name, cmd, icon, uses}], most relevant first, at most `limit`.
// With no query: the ones used most, then alphabetical.
function rank(apps, query, limit) {
    var q = String(query || "").trim();
    var out = [];
    for (var i = 0; i < apps.length; i++) {
        var a = apps[i];
        var m = match(a.name, q);
        if (q && m.score === 0 && String(a.cmd || "").toLowerCase().indexOf(q.toLowerCase()) < 0) continue;
        if (q && m.score === 0) m = { score: 60, start: 0, len: 0 };       // matched the command only
        var uses = Number(a.uses) || 0;
        // With nothing typed, plain usage decides. With a query, usage only
        // breaks ties among similar matches, and can never outweigh a better one.
        var score = q ? m.score + Math.min(60, Math.log(1 + uses) * 18) : uses;
        out.push({ app: a, score: score, start: m.start, len: m.len });
    }
    out.sort(function (x, y) {
        if (y.score !== x.score) return y.score - x.score;
        return String(x.app.name).toLowerCase() < String(y.app.name).toLowerCase() ? -1 : 1;
    });
    return limit > 0 ? out.slice(0, limit) : out;
}
