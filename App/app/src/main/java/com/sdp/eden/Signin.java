package com.sdp.eden;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.support.annotation.NonNull;
import android.support.design.widget.Snackbar;
import android.support.v7.app.AppCompatActivity;
import android.text.TextUtils;
import android.util.Log;
import android.util.Patterns;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;

import com.google.android.gms.tasks.OnCompleteListener;
import com.google.android.gms.tasks.Task;
import com.google.firebase.auth.AuthResult;
import com.google.firebase.auth.FirebaseAuth;
import com.google.firebase.auth.FirebaseUser;

import java.util.Objects;

public class Signin extends AppCompatActivity {
    private static final String TAG = "SignInActivity";

    private EditText mEmailField;
    private EditText mPasswordField;
    private FirebaseAuth mAuth;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        //Initializing variables
        super.onCreate(savedInstanceState);
        setContentView(R.layout.login_page);
        mAuth = FirebaseAuth.getInstance();
        mEmailField = findViewById(R.id.loginemailfield);
        mPasswordField = findViewById(R.id.loginpasswordfield);

        requestPermission();

        findViewById(R.id.sign_in_button).setOnClickListener(new View.OnClickListener(){
            public  void onClick(View v){
                signIn(mEmailField.getText().toString(), mPasswordField.getText().toString());
            }
        });

        findViewById(R.id.register).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                register(v);
            }
        });

        mEmailField.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override
            public void onFocusChange(View v, boolean hasFocus) {
                if (!hasFocus) {
                    hideKeyboard(v);
                }
            }
        });

        mPasswordField.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override
            public void onFocusChange(View v, boolean hasFocus) {
                if (!hasFocus) {
                    hideKeyboard(v);
                }
            }
        });
    }
       //On button register clicked, start Create_account
    public void register(View view){
        Intent intent=new Intent(this, Create_account.class);
        startActivity(intent);
    }



    private void signIn(String email, String password){
        //validate the input format
        if(!validateForm()){
            return;
        }
        mAuth.signInWithEmailAndPassword(email,password)
                .addOnCompleteListener(this, new OnCompleteListener<AuthResult>() {
                    @Override
                    public void onComplete(@NonNull Task<AuthResult> task) {
                        if (task.isSuccessful()){
                            FirebaseUser user = mAuth.getCurrentUser();

                            Log.d(TAG, "Signed in.");
                            Log.d(TAG, "User email is: "+user.getEmail());  // Bianca - added some logs.
                            updateUI(user);
                        } else{
                            Snackbar.make(findViewById(R.id.viewSnack), "Incorrect login, try again or register.", Snackbar.LENGTH_LONG).setAction("Register", new View.OnClickListener() {
                                @Override
                                public void onClick(View v) {
                                    startActivity(new Intent(Signin.this, Create_account.class));
                                }
                            }).setActionTextColor(Color.parseColor("#BB4444")).show(); // Kieran - changed toast to snackbar, displays error message and a button to take the user to register.
                            updateUI(null);
                        }

                    }
                });


    }

    private boolean validateForm() {
        boolean valid = true;
        //give error notice when format is incorrect
        String email = mEmailField.getText().toString();
        if (TextUtils.isEmpty(email)) {
            mEmailField.setError("Please enter your email!"); // Kieran - changing error messages to be more helpful
            valid = false;
        } else if(!Patterns.EMAIL_ADDRESS.matcher(email).matches()){
            mEmailField.setError("Try again");
        }
        else {
            mEmailField.setError(null);
        }

        String password = mPasswordField.getText().toString();
        if (TextUtils.isEmpty(password)) {
            mPasswordField.setError("Required.");
            valid = false;
        } else if(password.length()<6){
            mEmailField.setError("password requires at least 6 characters");
        }
        else {
            mPasswordField.setError(null);
        }

        return valid;
    }

    private void updateUI(FirebaseUser user) {
        //When user is not null proceed to main activity
        if (user != null) {

            Intent intent = new Intent(this, Eden_main.class);
            startActivity(intent);

        }
    }

    @Override
    protected void onStart (){
        super.onStart();
        //Automatically takes user to main activity when they are already logged in, until they chose to log out
        FirebaseUser user = mAuth.getCurrentUser();
        updateUI(user);
    }

    private void requestPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            requestPermissions(new String[] {
                    android.Manifest.permission.WRITE_EXTERNAL_STORAGE}, 1);
        } else {
            Snackbar permissionSnackbar = Snackbar.make(findViewById(R.id.viewSnack), "You must allow permissions", Snackbar.LENGTH_LONG);
            permissionSnackbar.setAction("Try Again", new PermissionAdd());
            permissionSnackbar.show();

        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);

        switch (requestCode) {
            case 1:
                if (grantResults.length > 0 && permissions[0].equals(Manifest.permission.WRITE_EXTERNAL_STORAGE)) {
                    // check whether storage permission granted or not.
                    if (grantResults[0] != PackageManager.PERMISSION_GRANTED) {

                        Snackbar permissionSnackbar = Snackbar.make(findViewById(R.id.viewSnack), "You must allow permissions", Snackbar.LENGTH_LONG);
                        permissionSnackbar.setAction("Try Again", new PermissionAdd());
                        permissionSnackbar.show();

                    }
                }
                break;
            default:
                break;
        }
    }


    public class PermissionAdd implements View.OnClickListener{

        @Override
        public void onClick(View v) {

            requestPermission();
        }
    }


    // https://stackoverflow.com/a/19828165/7038747
    public void hideKeyboard(View view) {
        InputMethodManager inputMethodManager =(InputMethodManager) getSystemService
                (Objects.requireNonNull(Activity.INPUT_METHOD_SERVICE));
        inputMethodManager.hideSoftInputFromWindow(view.getWindowToken(), 0);
    }

}
