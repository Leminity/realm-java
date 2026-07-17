package io.realm.ac08.fork;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

/** A deliberately network-free process probe used by the host force-stop phase. */
public final class ProbeActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        TextView text = new TextView(this);
        text.setText("AC08 fork probe");
        setContentView(text);
    }
}
