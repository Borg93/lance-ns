/**
 * Viewer registry — maps a media kind to its viewer component, so the annotator
 * route stays decoupled from any specific viewer. Adding a modality = one entry.
 */
import type { Component } from 'svelte';
import AudioViewer from './AudioViewer.svelte';
import ImageViewer from './ImageViewer.svelte';
import VideoViewer from './VideoViewer.svelte';
import type { MediaKind, ViewerProps } from './types';

/** Media kind from a MIME type — the descriptor's `document.mime` drives this. */
export function mediaKindOf(mime: string | null | undefined): MediaKind {
	const m = (mime ?? '').toLowerCase();
	if (m.startsWith('video/')) return 'video';
	if (m.startsWith('audio/')) return 'audio';
	return 'image';
}

const VIEWERS: Record<MediaKind, Component<ViewerProps>> = {
	image: ImageViewer,
	audio: AudioViewer,
	video: VideoViewer,
};

/** The viewer component for a media kind. */
export function viewerFor(kind: MediaKind): Component<ViewerProps> {
	return VIEWERS[kind];
}
