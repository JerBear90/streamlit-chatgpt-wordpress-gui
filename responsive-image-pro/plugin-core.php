<?php
// Hello World Shortcode
function hello_func() { return 'Hello World'; }
add_shortcode('hello_world', 'hello_func');