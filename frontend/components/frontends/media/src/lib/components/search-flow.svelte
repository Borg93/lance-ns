<script lang="ts">
	/** "How search works" — a concrete, visual explainer for non-experts.
      Renders inside the Help (?) popover (~520px wide). No props. */
</script>

<div class="flex flex-col gap-3 text-[11px]">
	<!-- 1) ONE-LINE FRAME -->
	<div class="border-border bg-card rounded-md border px-3 py-2">
		<span class="text-foreground">Every result is one </span>
		<strong class="text-primary">chunk</strong>
		<span class="text-muted-foreground">
			= a short transcript span + the video frame from that moment. Search ranks chunks.
		</span>
	</div>

	<!-- 2) THE 4 JUDGES -->
	<div class="flex flex-col gap-1.5">
		<div class="text-foreground font-semibold">The 4 judges</div>
		<p class="text-muted-foreground">
			A search asks up to four independent judges to rank the chunks. Each searches its
			<em>own</em> space and hands back its <em>own</em> ranked list. They never compare scores with each
			other.
		</p>
		<div class="grid grid-cols-2 gap-2">
			<div class="border-border bg-surface2 rounded border border-l-2 border-l-sky-400 p-2">
				<div class="text-foreground font-medium">⌨ Keyword</div>
				<div class="text-muted-foreground text-[10px]">
					exact words you type (FTS / BM25 on the transcript)
				</div>
			</div>
			<div class="border-border border-l-primary bg-surface2 rounded border border-l-2 p-2">
				<div class="text-foreground font-medium">💬 Meaning</div>
				<div class="text-muted-foreground text-[10px]">
					what a clip is about, even in other words (text vector)
				</div>
			</div>
			<div class="border-border bg-surface2 rounded border border-l-2 border-l-amber-400 p-2">
				<div class="text-foreground font-medium">🖼 Image</div>
				<div class="text-muted-foreground text-[10px]">
					how much the video frame looks like your image (frame vector)
				</div>
			</div>
			<div class="border-border bg-surface2 rounded border border-l-2 border-l-emerald-400 p-2">
				<div class="text-foreground font-medium">🎬 Scene</div>
				<div class="text-muted-foreground text-[10px]">
					what's visible on screen, from each frame's Swedish caption (caption vector)
				</div>
			</div>
		</div>
	</div>

	<!-- 3) PER-COMPONENT REFERENCE TABLE -->
	<div class="flex flex-col gap-1.5">
		<div class="text-foreground font-semibold">What each judge actually does</div>
		<div class="border-border overflow-hidden rounded border">
			<!-- header -->
			<div
				class="bg-surface2 text-foreground grid grid-cols-[64px_1fr_1fr] text-[10px] font-medium"
			>
				<div class="border-border border-b p-1.5">Judge</div>
				<div class="border-border border-b border-l p-1.5">You give it</div>
				<div class="border-border border-b border-l p-1.5">Compared against</div>
			</div>
			<!-- keyword -->
			<div class="text-muted-foreground grid grid-cols-[64px_1fr_1fr] text-[10px]">
				<div class="border-border text-foreground border-b p-1.5">⌨ Keyword</div>
				<div class="border-border border-b border-l p-1.5">your query words</div>
				<div class="border-border border-b border-l p-1.5">
					transcript text (BM25). Good at: exact terms, names.
				</div>
			</div>
			<!-- meaning -->
			<div class="text-muted-foreground grid grid-cols-[64px_1fr_1fr] text-[10px]">
				<div class="border-border text-foreground border-b p-1.5">💬 Meaning</div>
				<div class="border-border border-b border-l p-1.5">your text → a vector</div>
				<div class="border-border border-b border-l p-1.5">
					the <strong class="text-foreground">semantic vector</strong> of each transcript. Good at: topics,
					paraphrases.
				</div>
			</div>
			<!-- image -->
			<div class="text-muted-foreground grid grid-cols-[64px_1fr_1fr] text-[10px]">
				<div class="border-border text-foreground border-b p-1.5">🖼 Image</div>
				<div class="border-border border-b border-l p-1.5">your image → a vector</div>
				<div class="border-border border-b border-l p-1.5">
					<code>frame_embedding</code> of each video frame. Good at: visually similar scenes.
				</div>
			</div>
			<!-- scene -->
			<div class="text-muted-foreground grid grid-cols-[64px_1fr_1fr] text-[10px]">
				<div class="text-foreground p-1.5">🎬 Scene</div>
				<div class="border-border border-l p-1.5">your text → a vector</div>
				<div class="border-border border-l p-1.5">
					<code>caption_embedding</code> of each frame's Swedish caption. Good at: what's on screen ("plakat",
					"snöig gata").
				</div>
			</div>
		</div>
	</div>

	<!-- 4) FLOW DIAGRAM -->
	<div class="flex flex-col gap-1.5">
		<div class="text-foreground font-semibold">The whole pipeline</div>

		<!-- inputs -->
		<div class="grid grid-cols-3 gap-2">
			<div
				class="border-border bg-surface2 rounded border border-l-2 border-l-sky-400 px-2 py-1.5 text-center"
			>
				⌨ Keyword text
			</div>
			<div
				class="border-border border-l-primary bg-surface2 rounded border border-l-2 px-2 py-1.5 text-center"
			>
				💬 Meaning text
			</div>
			<div
				class="border-border bg-surface2 rounded border border-l-2 border-l-amber-400 px-2 py-1.5 text-center"
			>
				🖼 Image
			</div>
		</div>
		<div class="text-muted-foreground/70 grid grid-cols-3 text-center">
			<span>▼</span><span>▼ embed</span><span>▼ embed</span>
		</div>

		<!-- legs -->
		<div class="grid grid-cols-3 gap-2">
			<div class="border-border bg-background rounded border px-2 py-1.5 text-center">
				FTS leg
				<div class="text-muted-foreground text-[10px]">BM25 on text</div>
			</div>
			<div class="border-border bg-background rounded border px-2 py-1.5 text-center">
				Text-vector leg
				<div class="text-muted-foreground text-[10px]">the transcript's semantic vector</div>
			</div>
			<div class="border-border bg-background rounded border px-2 py-1.5 text-center">
				Frame-vector leg
				<div class="text-muted-foreground text-[10px]"><code>frame_embedding</code></div>
			</div>
		</div>
		<p class="text-muted-foreground/80 text-center text-[10px]">
			+ the text query also drives a <strong class="text-foreground">Scene</strong> leg (<code
				>caption_embedding</code
			>) in “all”.
		</p>
		<div class="text-muted-foreground/70 text-center">▼&emsp;&emsp;▼&emsp;&emsp;▼</div>

		<!-- fuse -->
		<div
			class="border-primary/50 bg-primary/10 text-foreground rounded-md border px-3 py-2 text-center font-medium"
		>
			Fuse into one ranking — RRF (default) or Balance slider (hybrid only)
		</div>
		<div class="text-muted-foreground/70 text-center">▼</div>

		<!-- rerank -->
		<div class="border-border bg-surface2 rounded border px-3 py-1.5 text-center">
			Rerank top <em>K</em> <span class="text-muted-foreground">(optional)</span> — re-read each transcript
			vs your text
		</div>
		<div class="text-muted-foreground/70 text-center">▼</div>

		<!-- results -->
		<div
			class="border-border bg-card text-foreground rounded-md border px-3 py-2 text-center font-semibold"
		>
			Top N ranked chunk results
		</div>
	</div>

	<!-- 5) RRF, CONCRETELY -->
	<div
		class="border-border bg-background flex flex-col gap-1.5 rounded-md border border-dashed p-2"
	>
		<div class="text-foreground font-semibold">How the lists merge: RRF (worked example)</div>
		<p class="text-muted-foreground">
			Two judges run on 5 clips (A–E) and each returns a ranked list:
		</p>
		<div class="grid grid-cols-2 gap-2 text-[10px]">
			<div class="border-border bg-surface2 rounded border p-1.5">
				<div class="text-foreground font-medium">⌨ Keyword</div>
				1 = C&ensp;·&ensp;2 = A&ensp;·&ensp;3 = B
			</div>
			<div class="border-border bg-surface2 rounded border p-1.5">
				<div class="text-foreground font-medium">💬 Meaning</div>
				1 = A&ensp;·&ensp;2 = C&ensp;·&ensp;3 = D
			</div>
		</div>
		<p class="text-muted-foreground">
			Each clip scores <code class="text-primary">sum of 1/(60 + rank)</code> over the lists it appears
			in:
		</p>
		<div
			class="border-border bg-surface2 text-foreground rounded border p-1.5 font-mono text-[10px]"
		>
			A = 1/62 + 1/61 ≈ 0.0326&ensp;<span class="bg-highlight/30 rounded px-1">in both → wins</span
			><br />
			C = 1/61 + 1/62 ≈ 0.0326&ensp;<span class="bg-highlight/30 rounded px-1">in both → wins</span
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
		<div class="text-foreground font-semibold">Balance slider vs RRF — the key difference</div>
		<p class="text-muted-foreground">
			The Balance slider is a <strong class="text-foreground">2-way blend</strong> of the actual
			scores; it only exists for Hybrid (keyword ↔ meaning). It cannot describe 3 legs, so the
			moment you add an image, fusion falls back to equal-weight RRF and the slider is
			<strong class="text-foreground">ignored</strong>.
		</p>
		<div class="grid grid-cols-2 gap-2 text-[10px]">
			<div class="border-border bg-surface2 rounded border p-2">
				<div class="text-foreground font-medium">Slider (2 judges only)</div>
				<div class="text-muted-foreground mt-0.5">Hybrid keyword ↔ meaning.</div>
				<div class="text-foreground mt-1 font-mono">w·vectorScore + (1−w)·ftsScore</div>
				<div class="text-muted-foreground mt-0.5">Uses real scores. You pick the weight.</div>
			</div>
			<div class="border-border bg-surface2 rounded border p-2">
				<div class="text-foreground font-medium">RRF (2 or 3 judges)</div>
				<div class="text-muted-foreground mt-0.5">Default everywhere; always for 3-way "all".</div>
				<div class="text-foreground mt-1 font-mono">Σ 1/(60 + rank)</div>
				<div class="text-muted-foreground mt-0.5">Uses ranks only. Equal weight, no tuning.</div>
			</div>
		</div>
	</div>

	<!-- 7) RERANK -->
	<div class="border-border bg-card flex flex-col gap-1.5 rounded-md border p-2">
		<div class="text-foreground font-semibold">Rerank (optional)</div>
		<ul class="text-muted-foreground list-disc space-y-0.5 pl-4">
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
		<div class="text-foreground font-semibold">⚙ Settings reference</div>
		<div class="border-border overflow-hidden rounded border text-[10px]">
			<div class="text-muted-foreground grid grid-cols-[1fr_1.6fr]">
				<div class="border-border text-foreground border-b p-1.5">Results to return</div>
				<div class="border-border border-b border-l p-1.5">
					How many chunks to show (N, default 100).
				</div>
			</div>
			<div class="text-muted-foreground grid grid-cols-[1fr_1.6fr]">
				<div class="border-border text-foreground border-b p-1.5">Rerank top</div>
				<div class="border-border border-b border-l p-1.5">
					Head size K the cross-encoder re-reads (default 20).
				</div>
			</div>
			<div class="text-muted-foreground grid grid-cols-[1fr_1.6fr]">
				<div class="border-border text-foreground border-b p-1.5">Balance</div>
				<div class="border-border border-b border-l p-1.5">
					Keyword ↔ meaning weight. Hybrid only (ignored once an image is added).
				</div>
			</div>
			<div class="text-muted-foreground grid grid-cols-[1fr_1.6fr]">
				<div class="text-foreground p-1.5">Match style</div>
				<div class="border-border border-l p-1.5">
					loose words, exact phrase, or fuzzy (typo-tolerant) keyword matching.
				</div>
			</div>
		</div>
	</div>

	<!-- 9) LIMITATIONS -->
	<div class="border-border bg-surface2 flex flex-col gap-1 rounded-md border p-2">
		<div class="text-foreground font-semibold">Known limitations</div>
		<ul class="text-muted-foreground list-disc space-y-0.5 pl-4">
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
