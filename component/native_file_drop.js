export default {
  template: '<div><slot /></div>',
  mounted() {
    this.onNativeFiles = (event) => {
      if (!this.$el.isConnected || this.$el.getClientRects().length === 0) return;
      this.$el.classList.toggle('file-hover', event.detail.hover === true);
      if (event.detail.ticket || event.detail.error) {
        this.$emit('selection', event.detail);
      }
    };
    window.addEventListener('calabash-native-files', this.onNativeFiles);
  },
  beforeUnmount() {
    window.removeEventListener('calabash-native-files', this.onNativeFiles);
  },
};
