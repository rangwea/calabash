export default {
  template: '<div><slot /></div>',
  props: { imageUploadUrl: String },
  methods: {
    visible() { return this.$el.isConnected && this.$el.getClientRects().length > 0; },
    uploadDone() {
      this.uploading = false;
      delete this.$el.dataset.uploading;
    },
    async uploadImages(files) {
      if (!files.length || !this.imageUploadUrl) return;
      if (this.uploading) { this.$emit('selection', {error: 'upload_busy'}); return; }
      if (files.length > 5 || files.some(file => file.size > 10 * 1024 * 1024)) {
        this.$emit('selection', {error: files.length > 5 ? 'image_count' : 'image_limit'}); return;
      }
      this.uploading = true;
      this.$el.dataset.uploading = 'true';
      this.$emit('imageUploading', {busy: true});
      try {
        const body = new FormData();
        files.forEach((file, index) => body.append('image_' + index, file, file.name || 'pasted-image.png'));
        const response = await fetch((window.path_prefix || '') + this.imageUploadUrl, {method: 'POST', body});
        if (!response.ok) throw new Error('upload_failed');
      } catch (_) {
        this.$emit('selection', {error: 'upload_failed'});
        this.uploadDone();
        this.$emit('imageUploading', {busy: false});
      }
    },
  },
  mounted() {
    this.onNativeFiles = (event) => {
      if (!this.visible()) return;
      this.$el.classList.toggle('file-hover', event.detail.hover === true);
      if (event.detail.ticket || event.detail.error) this.$emit('selection', event.detail);
    };
    this.onPaste = (event) => {
      if (!this.visible()) return;
      const files = Array.from(event.clipboardData?.items || [])
        .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
        .map(item => item.getAsFile()).filter(Boolean);
      if (files.length) { event.preventDefault(); this.uploadImages(files); }
    };
    this.onDragOver = (event) => {
      if (!this.visible() || window.__TAURI_INTERNALS__) return;
      if (Array.from(event.dataTransfer?.items || []).some(item => item.type.startsWith('image/'))) {
        event.preventDefault(); this.$el.classList.add('file-hover');
      }
    };
    this.onDrop = (event) => {
      if (!this.visible() || window.__TAURI_INTERNALS__) return;
      const files = Array.from(event.dataTransfer?.files || []).filter(file => file.type.startsWith('image/'));
      this.$el.classList.remove('file-hover');
      if (files.length) { event.preventDefault(); this.uploadImages(files); }
    };
    this.onLeave = () => this.$el.classList.remove('file-hover');
    window.addEventListener('calabash-native-files', this.onNativeFiles);
    this.$el.addEventListener('paste', this.onPaste);
    this.$el.addEventListener('dragover', this.onDragOver);
    this.$el.addEventListener('dragleave', this.onLeave);
    this.$el.addEventListener('drop', this.onDrop);
  },
  beforeUnmount() {
    window.removeEventListener('calabash-native-files', this.onNativeFiles);
    this.$el.removeEventListener('paste', this.onPaste);
    this.$el.removeEventListener('dragover', this.onDragOver);
    this.$el.removeEventListener('dragleave', this.onLeave);
    this.$el.removeEventListener('drop', this.onDrop);
  },
};
