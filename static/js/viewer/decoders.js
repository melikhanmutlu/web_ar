/* Registers the self-hosted decoders on <model-viewer>. Loaded synchronously in
   <head>; the URLs arrive as data-* attributes on this script tag.
   Meshopt-compressed GLBs need the meshopt decoder registered before
   model-viewer loads one, or the model silently never renders (model-viewer
   ships a DRACO decoder default but has no meshopt default). DRACO / KTX2 are
   self-hosted too (model-viewer defaults to www.gstatic.com). */
(function () {
    var data = document.currentScript.dataset;
    customElements.whenDefined('model-viewer').then(function () {
        var MV = customElements.get('model-viewer');
        MV.meshoptDecoderLocation = data.meshopt;
        MV.dracoDecoderLocation = data.draco;
        MV.ktx2TranscoderLocation = data.ktx2;
    });
})();
