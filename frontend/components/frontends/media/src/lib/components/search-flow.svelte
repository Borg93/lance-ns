<script lang="ts">
  /** "How search works" — a concrete, visual explainer for non-experts.
      Renders inside the Help (?) popover (~520px wide). No props. */
</script>

<div class="flex flex-col gap-3 text-[11px]">
  <!-- 1) ONE-LINE FRAME -->
  <div class="rounded-md border border-border bg-card px-3 py-2">
    <span class="text-foreground">Every result is one </span>
    <strong class="text-primary">chunk</strong>
    <span class="text-muted-foreground">
      = a short transcript span + the video frame from that moment. Search ranks chunks.
    </span>
  </div>

  <!-- 2) THE 4 JUDGES -->
  <div class="flex flex-col gap-1.5">
    <div class="font-semibold text-foreground">The 4 judges</div>
    <p class="text-muted-foreground">
      A search asks up to four independent judges to rank the chunks. Each searches its
      <em>own</em> space and hands back its <em>own</em> ranked list. They never compare scores with each
      other.
    </p>
    <div class="grid grid-cols-2 gap-2">
      <div class="rounded border border-border border-l-2 border-l-sky-400 bg-surface2 p-2">
        <div class="font-medium text-foreground">⌨ Keyword</div>
        <div class="text-[10px] text-muted-foreground">
          exact words you type (FTS / BM25 on the transcript)
        </div>
      </div>
      <div class="rounded border border-border border-l-2 border-l-primary bg-surface2 p-2">
        <div class="font-medium text-foreground">💬 Meaning</div>
        <div class="text-[10px] text-muted-foreground">
          what a clip is about, even in other words (text vector)
        </div>
      </div>
      <div class="rounded border border-border border-l-2 border-l-amber-400 bg-surface2 p-2">
        <div class="font-medium text-foreground">🖼 Image</div>
        <div class="text-[10px] text-muted-foreground">
          how much the video frame looks like your image (frame vector)
        </div>
      </div>
      <div class="rounded border border-border border-l-2 border-l-emerald-400 bg-surface2 p-2">
        <div class="font-medium text-foreground">🎬 Scene</div>
        <div class="text-[10px] text-muted-foreground">
          what's visible on screen, from each frame's Swedish caption (caption vector)
        </div>
      </div>
    </div>
  </div>

  <!-- 3) PER-COMPONENT REFERENCE TABLE -->
  <div class="flex flex-col gap-1.5">
    <div class="font-semibold text-foreground">What each judge actually does</div>
    <div class="overflow-hidden rounded border border-border">
      <!-- header -->
      <div
        class="grid grid-cols-[64px_1fr_1fr] bg-surface2 text-[10px] font-medium text-foreground"
      >
        <div class="border-b border-border p-1.5">Judge</div>
        <div class="border-b border-l border-border p-1.5">You give it</div>
        <div class="border-b border-l border-border p-1.5">Compared against</div>
      </div>
      <!-- keyword -->
      <div class="grid grid-cols-[64px_1fr_1fr] text-[10px] text-muted-foreground">
        <div class="border-b border-border p-1.5 text-foreground">⌨ Keyword</div>
        <div class="border-b border-l border-border p-1.5">your query words</div>
        <div class="border-b border-l border-border p-1.5">
          transcript text (BM25). Good at: exact terms, names.
        </div>
      </div>
      <!-- meaning -->
      <div class="grid grid-cols-[64px_1fr_1fr] text-[10px] text-muted-foreground">
        <div class="border-b border-border p-1.5 text-foreground">💬 Meaning</div>
        <div class="border-b border-l border-border p-1.5">your text → a vector</div>
        <div class="border-b border-l border-border p-1.5">
          the <strong class="text-foreground">semantic vector</strong> of each transcript. Good at: topics,
          paraphrases.
        </div>
      </div>
      <!-- image -->
      <div class="grid grid-cols-[64px_1fr_1fr] text-[10px] text-muted-foreground">
        <div class="border-b border-border p-1.5 text-foreground">🖼 Image</div>
        <div class="border-b border-l border-border p-1.5">your image → a vector</div>
        <div class="border-b border-l border-border p-1.5">
          <code>frame_embedding</code> of each video frame. Good at: visually similar scenes.
        </div>
      </div>
      <!-- scene -->
      <div class="grid grid-cols-[64px_1fr_1fr] text-[10px] text-muted-foreground">
        <div class="p-1.5 text-foreground">🎬 Scene</div>
        <div class="border-l border-border p-1.5">your text → a vector</div>
        <div class="border-l border-border p-1.5">
          <code>caption_embedding</code> of each frame's Swedish caption. Good at: what's on screen ("plakat",
          "snöig gata").
        </div>
      </div>
    </div>
  </div>

  <!-- 4) FLOW DIAGRAM -->
  <div class="flex flex-col gap-1.5">
    <div class="font-semibold text-foreground">The whole pipeline</div>

    <!-- inputs -->
    <div class="grid grid-cols-3 gap-2">
      <div
        class="rounded border border-border border-l-2 border-l-sky-400 bg-surface2 px-2 py-1.5 text-center"
      >
        ⌨ Keyword text
      </div>
      <div
        class="rounded border border-border border-l-2 border-l-primary bg-surface2 px-2 py-1.5 text-center"
      >
        💬 Meaning text
      </div>
      <div
        class="rounded border border-border border-l-2 border-l-amber-400 bg-surface2 px-2 py-1.5 text-center"
      >
        🖼 Image
      </div>
    </div>
    <div class="grid grid-cols-3 text-center text-muted-foreground/70">
      <span>▼</span><span>▼ embed</span><span>▼ embed</span>
    </div>

    <!-- legs -->
    <div class="grid grid-cols-3 gap-2">
      <div class="rounded border border-border bg-background px-2 py-1.5 text-center">
        FTS leg
        <div class="text-[10px] text-muted-foreground">BM25 on text</div>
      </div>
      <div class="rounded border border-border bg-background px-2 py-1.5 text-center">
        Text-vector leg
        <div class="text-[10px] text-muted-foreground">the transcript's semantic vector</div>
      </div>
      <div class="rounded border border-border bg-background px-2 py-1.5 text-center">
        Frame-vector leg
        <div class="text-[10px] text-muted-foreground"><code>frame_embedding</code></div>
      </div>
    </div>
    <p class="text-center text-[10px] text-muted-foreground/80">
      + the text query also drives a <strong class="text-foreground">Scene</strong> leg (<code
        >caption_embedding</code
      >) in “all”.
    </p>
    <div class="text-center text-muted-foreground/70">▼&emsp;&emsp;▼&emsp;&emsp;▼</div>

    <!-- fuse -->
    <div
      class="rounded-md border border-primary/50 bg-primary/10 px-3 py-2 text-center font-medium text-foreground"
    >
      Fuse into one ranking — RRF (default) or Balance slider (hybrid only)
    </div>
    <div class="text-center text-muted-foreground/70">▼</div>

    <!-- rerank -->
    <div class="rounded border border-border bg-surface2 px-3 py-1.5 text-center">
      Rerank top <em>K</em> <span class="text-muted-foreground">(optional)</span> — re-read each transcript
      vs your text
    </div>
    <div class="text-center text-muted-foreground/70">▼</div>

    <!-- results -->
    <div
      class="rounded-md border border-border bg-card px-3 py-2 text-center font-semibold text-foreground"
    >
      Top N ranked chunk results
    </div>
  </div>

  <!-- 5) RRF, CONCRETELY -->
  <div
    class="flex flex-col gap-1.5 rounded-md border border-dashed border-border bg-background p-2"
  >
    <div class="font-semibold text-foreground">How the lists merge: RRF (worked example)</div>
    <p class="text-muted-foreground">
      Two judges run on 5 clips (A–E) and each returns a ranked list:
    </p>
    <div class="grid grid-cols-2 gap-2 text-[10px]">
      <div class="rounded border border-border bg-surface2 p-1.5">
        <div class="font-medium text-foreground">⌨ Keyword</div>
        1 = C&ensp;·&ensp;2 = A&ensp;·&ensp;3 = B
      </div>
      <div class="rounded border border-border bg-surface2 p-1.5">
        <div class="font-medium text-foreground">💬 Meaning</div>
        1 = A&ensp;·&ensp;2 = C&ensp;·&ensp;3 = D
      </div>
    </div>
    <p class="text-muted-foreground">
      Each clip scores <code class="text-primary">sum of 1/(60 + rank)</code> over the lists it appears
      in:
    </p>
    <div
      class="rounded border border-border bg-surface2 p-1.5 font-mono text-[10px] text-foreground"
    >
      A = 1/62 + 1/61 ≈ 0.0326&ensp;<span class="rounded bg-highlight/30 px-1">in both → wins</span
      ><br />
      C = 1/61 + 1/62 ≈ 0.0326&ensp;<span class="rounded bg-highlight/30 px-1">in both → wins</span
      ><br />
      B = 1/63 &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;&ensp;&ensp;≈ 0.0159 (one list)<br />
      D = 1/63 &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;&ensp;&ensp;≈ 0.0159 (one list)
    </div>
    <p class="text-muted-foreground">
      Clips that appear in <strong class="text-foreground">more lists</strong> rise to the top. RRF
      needs no tuning and works the same for
      <strong class="text-foreground">2, 3, or 4 lists</strong>
      — you just add another
      <code>1/(60 + rank)</code> term. The multi-judge "all" mode <em>always</em> uses equal-weight RRF.
    </p>
  </div>

  <!-- 6) SLIDER vs RRF -->
  <div class="flex flex-col gap-1.5">
    <div class="font-semibold text-foreground">Balance slider vs RRF — the key difference</div>
    <p class="text-muted-foreground">
      The Balance slider is a <strong class="text-foreground">2-way blend</strong> of the actual
      scores; it only exists for Hybrid (keyword ↔ meaning). It cannot describe 3 legs, so the
      moment you add an image, fusion falls back to equal-weight RRF and the slider is
      <strong class="text-foreground">ignored</strong>.
    </p>
    <div class="grid grid-cols-2 gap-2 text-[10px]">
      <div class="rounded border border-border bg-surface2 p-2">
        <div class="font-medium text-foreground">Slider (2 judges only)</div>
        <div class="mt-0.5 text-muted-foreground">Hybrid keyword ↔ meaning.</div>
        <div class="mt-1 font-mono text-foreground">w·vectorScore + (1−w)·ftsScore</div>
        <div class="mt-0.5 text-muted-foreground">Uses real scores. You pick the weight.</div>
      </div>
      <div class="rounded border border-border bg-surface2 p-2">
        <div class="font-medium text-foreground">RRF (2 or 3 judges)</div>
        <div class="mt-0.5 text-muted-foreground">Default everywhere; always for 3-way "all".</div>
        <div class="mt-1 font-mono text-foreground">Σ 1/(60 + rank)</div>
        <div class="mt-0.5 text-muted-foreground">Uses ranks only. Equal weight, no tuning.</div>
      </div>
    </div>
  </div>

  <!-- 7) RERANK -->
  <div class="flex flex-col gap-1.5 rounded-md border border-border bg-card p-2">
    <div class="font-semibold text-foreground">Rerank (optional)</div>
    <ul class="list-disc space-y-0.5 pl-4 text-muted-foreground">
      <li>
        Takes only the <strong class="text-foreground">top K</strong> (default 20) of the already-fused
        list.
      </li>
      <li>
        A cross-encoder re-reads each of those transcripts against your combined text (<code
          >keyword + meaning</code
        >) and reorders just that head.
      </li>
      <li>Everything below K keeps its first-stage order — no second search is run.</li>
      <li>
        <strong class="text-foreground">Text-only:</strong> it never looks at the image or the vectors.
        For image-only search there is no query text, so rerank is a no-op.
      </li>
    </ul>
  </div>

  <!-- 8) SETTINGS REFERENCE -->
  <div class="flex flex-col gap-1.5">
    <div class="font-semibold text-foreground">⚙ Settings reference</div>
    <div class="overflow-hidden rounded border border-border text-[10px]">
      <div class="grid grid-cols-[1fr_1.6fr] text-muted-foreground">
        <div class="border-b border-border p-1.5 text-foreground">Results to return</div>
        <div class="border-b border-l border-border p-1.5">
          How many chunks to show (N, default 100).
        </div>
      </div>
      <div class="grid grid-cols-[1fr_1.6fr] text-muted-foreground">
        <div class="border-b border-border p-1.5 text-foreground">Rerank top</div>
        <div class="border-b border-l border-border p-1.5">
          Head size K the cross-encoder re-reads (default 20).
        </div>
      </div>
      <div class="grid grid-cols-[1fr_1.6fr] text-muted-foreground">
        <div class="border-b border-border p-1.5 text-foreground">Balance</div>
        <div class="border-b border-l border-border p-1.5">
          Keyword ↔ meaning weight. Hybrid only (ignored once an image is added).
        </div>
      </div>
      <div class="grid grid-cols-[1fr_1.6fr] text-muted-foreground">
        <div class="p-1.5 text-foreground">Match style</div>
        <div class="border-l border-border p-1.5">
          loose words, exact phrase, or fuzzy (typo-tolerant) keyword matching.
        </div>
      </div>
    </div>
  </div>

  <!-- 9) LIMITATIONS -->
  <div class="flex flex-col gap-1 rounded-md border border-border bg-surface2 p-2">
    <div class="font-semibold text-foreground">Known limitations</div>
    <ul class="list-disc space-y-0.5 pl-4 text-muted-foreground">
      <li>
        Image search = visual <strong class="text-foreground">frame similarity</strong>, not face /
        identity recognition.
      </li>
      <li>
        Speaker diarization shows <em>who speaks when</em>, but nothing links who is
        <em>on screen</em> to who is <em>speaking</em>.
      </li>
      <li>The reranker is text-only; it never uses the image.</li>
      <li>Multi-leg fusion (up to 4 judges) is equal-weight — there is no per-leg weight yet.</li>
      <li>Scene depends on AI captions — only as accurate as the frame captioner.</li>
    </ul>
  </div>
</div>
