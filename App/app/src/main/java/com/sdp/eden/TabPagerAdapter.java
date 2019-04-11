package com.sdp.eden;

import android.support.v4.app.Fragment;
import android.support.v4.app.FragmentManager;
import android.support.v4.app.FragmentPagerAdapter;

public class TabPagerAdapter extends FragmentPagerAdapter {

    public static ScheduleFragment scheduleFragmentInstance;
    TabPagerAdapter(FragmentManager fm){super(fm);}

    @Override
    public Fragment getItem(int i) {
        switch(i){
            default: return new Plant_Cards_Fragment().newInstance();
            case 1:
                scheduleFragmentInstance = new ScheduleFragment();
                return scheduleFragmentInstance;
    }
    }

    @Override
    public int getCount() {
        return 2;
    }

    public CharSequence getPageTitle(int position) {
        //this determines the titles displayed on each tab
        if(position==0) {
            return "Plants";
        }else {
            return "Schedule";
        }
    }
}
