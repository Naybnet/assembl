'use strict';

var Marionette = require('../shims/marionette.js'),
    _ = require('../shims/underscore.js'),
    Assembl = require('../app.js'),
    Ctx = require('../common/context.js');


var LoaderView = Marionette.ItemView.extend({
  template: '#tmpl-loader',
    
  onRender: function () {
    // Get rid of that pesky wrapping-div.
    // Assumes 1 child element present in template.
    this.$el = this.$el.children();
    // Unwrap the element to prevent infinitely 
    // nesting elements during re-render.
    this.$el.unwrap();
    this.setElement(this.$el);
  }
});

module.exports = LoaderView;